# Why MarkovJunior is used for benchmarking

ArchiE Graphs uses [MarkovJunior, originally developed by Maxim Gumin](https://github.com/mxgmn/MarkovJunior), as a manageable case study for architecture question answering. The original project is a probabilistic programming language based on rewrite rules and constraint propagation. The selection rationale below concerns the local benchmark snapshot, rather than a claim that every upstream version has identical structure.

## Architectural coverage

MarkovJunior combines a coherent application purpose with relationships distributed across classes. The inspected local `source/` directory contains 26 C# files and approximately 4,332 lines, making manual source inspection and independent annotation practical. Small size does not make every algorithm simple, but it limits the amount of code reviewers must navigate.

The application has a distinct initialization and execution lifecycle. `Interpreter.Load` creates the grid and constructs the node hierarchy. `Interpreter.Run` initializes the random generator, clears the grid, resets nodes and advances execution until its loop condition fails. These stages support questions about initialization, object creation, state management, dependencies and termination. Relevant facts can be checked against [Interpreter.cs](../ignore/MarkovJunior/source/Interpreter.cs).

Inheritance supports questions requiring multiple structural steps. `SequenceNode` and `MarkovNode` inherit from `Branch`, which inherits from `Node`. Abstract methods and overrides also let the benchmark distinguish static symbol resolution from runtime dispatch. See [Node.cs](../ignore/MarkovJunior/source/Node.cs).

The project uses framework interfaces: `StateComparer` implements `IEqualityComparer<byte[]>` in [Search.cs](../ignore/MarkovJunior/source/Search.cs). However, its central execution abstractions are abstract classes, and the current extractor omits external framework relationships. This interface use therefore does not establish that the benchmark exercises extracted interface edges. The [controlled C# fixture](../fixtures/csharp/Core/Service.cs) supplies a project-defined interface and remains necessary for testing that relationship; its [controller](../fixtures/csharp/App/Controller.cs) also covers constructor injection.

MarkovJunior produces concrete artifacts through a pipeline connecting configuration loading, interpretation, rendering and file writing. [Program.cs](../ignore/MarkovJunior/source/Program.cs) selects PNG or VOX output after consuming interpreter results. This supports questions about component responsibilities and the flow from execution to output. Generated artifacts also make demonstrations understandable, although a correct image does not validate an architectural answer.

## Additional advantages

The repository supplies XML models and explanatory documentation, giving reviewers examples with which to understand the application. Its explicit random-seed parameter supports repeatable demonstrations when the model, configuration and runtime conditions are controlled. The [MIT licence](https://github.com/mxgmn/MarkovJunior/blob/main/LICENSE) facilitates reuse subject to its attribution and notice requirements.

Unlike a synthetic fixture, this application contains naturally occurring relationships and domain logic. It can expose retrieval and reasoning problems that a deliberately simplified test might miss. Conversely, the small fixture provides precise control over individual relationships. The two sources serve complementary purposes.

Visual examples and clear progression from simple rules to generated patterns make its basic purpose accessible to readers with varied programming backgrounds.

## Limitations and evaluation controls

- **Limited generalisability:** a small, single-project procedural-generation application does not represent large enterprise systems, cross-project dependencies or service architectures. Include additional repositories before making broad claims.
- **Domain complexity:** rewrite rules, constraint propagation and generation algorithms can require substantial background knowledge. Review questions for ambiguity and distinguish architectural evidence from algorithmic interpretation.
- **Static-analysis boundaries:** XML configuration, polymorphism and runtime state affect behaviour beyond what static dependency edges establish. Phrase questions around supported static facts and avoid claiming a uniquely resolved runtime implementation without evidence.
- **Small-context effects:** source retrieval may already provide enough evidence on a compact project, leaving little benefit for graph augmentation. Record actual token usage and assess results by dependency depth rather than assuming graph mode should win.
- **Development exposure:** questions used to tune prompts, retrieval or graph selection are calibration material. Freeze separately reviewed held-out questions before formal comparison.
- **Snapshot provenance and build conditions:** the vendored snapshot has no verified upstream Git revision. Preserve the benchmark's source content hash, local modifications, dependency versions and diagnostics; do not describe it as a verified upstream commit. Review existing build and package warnings before further execution.

MarkovJunior is therefore an inspectable case study alongside the fixture and further repositories. It provides useful architectural variety at a manageable review cost, while formal claims still require approved labels, independent factual grading and controlled paired experiments. See the [evaluation protocol](PROTOCOL.md) and [benchmark review packet](REVIEW.md).

## Original project citation

Gumin, M. (n.d.). *MarkovJunior* [Computer software]. GitHub. https://github.com/mxgmn/MarkovJunior

The upstream citation identifies the original project. Counts and implementation examples above describe the inspected local snapshot; they are not measurements of the current upstream branch.
