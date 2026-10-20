using System.Security.Cryptography;
using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.MSBuild;

MSBuildLocator.RegisterDefaults();
try
{
    using var request = JsonDocument.Parse(await Console.In.ReadToEndAsync());
    var input = Path.GetFullPath(request.RootElement.GetProperty("input").GetProperty("path").GetString()!);
    var timeout = request.RootElement.GetProperty("options").GetProperty("timeout_seconds").GetInt32();
    using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(timeout));
    var token = cancellation.Token;
    var root = Path.GetDirectoryName(input)!;
    using var workspace = MSBuildWorkspace.Create();
    var diagnostics = new ConcurrentBag<object>();
    void Diagnostic(string code, string message) => diagnostics.Add(new {
        code, severity = "warning", message, component = "roslyn", recoverable = true
    });
    using var workspaceErrors = workspace.RegisterWorkspaceFailedHandler(e => Diagnostic("WORKSPACE_WARNING", e.Diagnostic.Message));
    Solution solution;
    if (Path.GetExtension(input) == ".sln")
        solution = await workspace.OpenSolutionAsync(input, cancellationToken: token);
    else
        solution = (await workspace.OpenProjectAsync(input, cancellationToken: token)).Solution;

    string Relative(string path)
    {
        var relative = Path.GetRelativePath(root, path).Replace('\\', '/');
        if (relative == ".." || relative.StartsWith("../") || Path.IsPathRooted(relative))
            throw new InvalidOperationException("Source or project lies outside the input directory");
        return relative;
    }
    string ProjectId(Project project) => "project:" + Uri.EscapeDataString(Relative(project.FilePath!));
    var projects = solution.Projects.OrderBy(p => p.FilePath, StringComparer.Ordinal).ToArray();
    var nodes = new SortedDictionary<string, object>(StringComparer.Ordinal);
    var edges = new SortedDictionary<string, object>(StringComparer.Ordinal);
    var symbols = new Dictionary<ISymbol, string>(SymbolEqualityComparer.Default);
    var symbolIds = new Dictionary<string, string>(StringComparer.Ordinal);
    string Key(ISymbol symbol) => symbol.ContainingAssembly.Identity + "|" + symbol.OriginalDefinition.GetDocumentationCommentId();
    var documents = new List<(Document Document, SyntaxNode Syntax, SemanticModel Model, Project Project)>();
    object Span(SyntaxNode syntax)
    {
        var text = syntax.SyntaxTree.GetText(token);
        var start = text.Lines.GetLinePosition(syntax.SpanStart);
        var end = text.Lines.GetLinePosition(Math.Max(syntax.SpanStart, syntax.Span.End - 1));
        return new { path = Relative(syntax.SyntaxTree.FilePath), start_line = start.Line + 1,
            start_column = start.Character + 1, end_line = end.Line + 1, end_column = end.Character + 1 };
    }
    foreach (var project in projects)
    {
        foreach (var document in project.Documents.OrderBy(d => d.FilePath, StringComparer.Ordinal))
        {
            if (document.FilePath is null || document.FilePath.Split(Path.DirectorySeparatorChar).Contains("obj")) continue;
            Relative(document.FilePath);
            var syntax = await document.GetSyntaxRootAsync(token);
            var model = await document.GetSemanticModelAsync(token);
            if (syntax is null || model is null) continue;
            documents.Add((document, syntax, model, project));
            foreach (var error in model.GetDiagnostics(cancellationToken: token).Where(d => d.Severity == DiagnosticSeverity.Error))
                Diagnostic("UNRESOLVED_SYMBOL", error.ToString());
            foreach (var declaration in syntax.DescendantNodes().Where(n => n is BaseTypeDeclarationSyntax or BaseMethodDeclarationSyntax))
            {
                var symbol = model.GetDeclaredSymbol(declaration, token);
                if (symbol is null) continue;
                var kind = symbol is INamedTypeSymbol ? "type" : "method";
                var id = kind + ":" + Uri.EscapeDataString(Relative(project.FilePath!)) + ":" + Uri.EscapeDataString(symbol.GetDocumentationCommentId()!);
                symbols[symbol] = id;
                symbolIds[Key(symbol)] = id;
                nodes[id] = new { id, kind, name = symbol.Name,
                    qualified_name = symbol.ToDisplayString(), project_id = ProjectId(project), source = Span(declaration) };
            }
        }
    }
    string? Find(ISymbol? symbol)
    {
        if (symbol is null) return null;
        symbol = symbol.OriginalDefinition;
        return symbols.TryGetValue(symbol, out var id) ? id : symbolIds.GetValueOrDefault(Key(symbol));
    }
    void Edge(ISymbol? from, ISymbol? to, string kind, SyntaxNode syntax)
    {
        var source = Find(from);
        var target = Find(to);
        if (source is null || target is null) return; // External framework symbols are outside this index.
        var span = Span(syntax);
        var identity = source + "|" + target + "|" + kind + "|" + JsonSerializer.Serialize(span);
        var id = "edge:" + Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(identity)));
        edges[id] = new { id, from = source, to = target, kind, status = "extracted", source = span, confidence = 1.0 };
    }
    foreach (var (_, syntax, model, _) in documents)
    {
        foreach (var declaration in syntax.DescendantNodes().OfType<TypeDeclarationSyntax>())
        {
            var symbol = model.GetDeclaredSymbol(declaration, token);
            if (symbol is null || declaration.BaseList is null) continue;
            foreach (var parent in declaration.BaseList.Types)
            {
                var target = model.GetTypeInfo(parent.Type, token).Type;
                Edge(symbol, target, target?.TypeKind == TypeKind.Interface ? "implements" : "inherits", parent.Type);
            }
        }
        foreach (var call in syntax.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var method = model.GetSymbolInfo(call, token).Symbol as IMethodSymbol;
            if (method is null) { Diagnostic("UNRESOLVED_CALL", "Unresolved call in " + Relative(call.SyntaxTree.FilePath)); continue; }
            var enclosing = model.GetEnclosingSymbol(call.SpanStart, token);
            while (enclosing is not null && enclosing is not IMethodSymbol) enclosing = enclosing.ContainingSymbol;
            Edge(enclosing, method.ReducedFrom ?? method, "calls", call);
        }
    }
    // Include project metadata and source bytes, but never generated build output.
    using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    var files = documents.Select(d => d.Document.FilePath!).Concat(projects.Select(p => p.FilePath!)).Append(input)
        .Distinct().OrderBy(p => Relative(p), StringComparer.Ordinal);
    foreach (var file in files)
    {
        var bytes = await File.ReadAllBytesAsync(file, token);
        hash.AppendData(Encoding.UTF8.GetBytes(Relative(file) + "\0" + bytes.Length + "\0"));
        hash.AppendData(bytes);
    }
    var result = new {
        schema_version = "archie.extractor-result.v1", schema_revision = 1,
        extractor = new { id = "roslyn", version = "0.1.0", interface_version = "archie.extractor-interface.v1",
            capabilities = new[] { "types", "methods", "inherits", "implements", "calls" } },
        input = new { path = input, content_hash = "sha256:" + Convert.ToHexStringLower(hash.GetHashAndReset()) },
        status = diagnostics.Count == 0 ? "succeeded" : "partial",
        projects = projects.Select(p => new { id = ProjectId(p), name = p.Name, path = Relative(p.FilePath!) }),
        nodes = nodes.Values, edges = edges.Values,
        diagnostics = diagnostics.OrderBy(d => JsonSerializer.Serialize(d), StringComparer.Ordinal)
    };
    Console.WriteLine(JsonSerializer.Serialize(result));
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
return 0;
