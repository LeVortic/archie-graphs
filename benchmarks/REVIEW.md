# Benchmark review required

Primary focus selected by the project owner: factual correctness on multi-hop C# architecture questions. The wording, scoring protocol, expected facts, and citations below remain draft and need human review.

## Research question

Does source-backed dependency-graph context improve factual correctness on multi-hop C# architecture questions, compared with source-only retrieval using the same local model and context ceiling?

## Proposed operational measure

Primary subset: questions annotated dependency_depth >= 2. Proposed primary metric: macro-average human-annotated atomic-fact F1 on that subset, with precision and recall reported separately. See PROTOCOL.md for the review procedure and edge cases. This scoring definition is proposed, not yet approved.

The development packet currently contains five primary multi-hop questions and eleven controls. It is not a sufficient held-out research dataset. Some questions were used during development; do not report them as held-out evidence.

## Your review

1. Confirm or revise research-question wording and the proposed fact-F1 measure.
2. Check each expected fact against its cited source; split compound facts and remove unasked requirements.
3. Check dependency depth, category, acceptable citations, and abstention cases.
4. Keep abstention labels about insufficient evidence rather than proving repository-wide absence.
5. Report corrections and reviewer name/date. Only after explicit review should JSON review metadata become approved.

Passing structural citation checks does not establish factual correctness or relevance. MarkovJunior has no verified upstream commit in this local snapshot; its indexed content hash is recorded instead. Actual token usage can differ between modes and must be reported; equal ceilings alone do not isolate a causal graph benefit.

## fixture

Source content hash: `sha256:450aba2d1f8f30230a7cda5eda6481632adabd6b9ca0515db80eadaccd4a1f7d`

### question:fixture-interface

Which interface does Fixture.Core.Service implement?

Subset: control; category: local_fact; depth: 0; expected action: answer.

- Fixture.Core.Service implements Fixture.Core.IService.

Acceptable source regions: Core/Service.cs:3-7.

### question:fixture-injection

Which indexed type does Fixture.App.Controller receive in its constructor and store in its service field?

Subset: control; category: dependency; depth: 1; expected action: answer.

- Controller receives an IService constructor parameter.
- The service field has declared type IService.

Acceptable source regions: App/Controller.cs:7-8.

### question:fixture-call

What is the statically resolved target of the call in Fixture.App.Controller.Handle?

Subset: control; category: dependency; depth: 1; expected action: answer.

- Controller.Handle calls the declared IService.Run method.

Acceptable source regions: App/Controller.cs:9-9, Core/Service.cs:3-7.

Review note: Do not require an unasked runtime caveat for full fact recall; any definite runtime-implementation claim must be checked separately.

### question:fixture-base-path

What type-dependency path connects Fixture.App.Controller to Fixture.Core.BaseService?

Subset: primary multi-hop; category: path; depth: 2; expected action: answer.

- Controller creates Service instances, giving an extracted constructor-use dependency on Service.
- Service inherits BaseService, giving the path Controller to Service to BaseService.

Acceptable source regions: App/Controller.cs:10-11, Core/Service.cs:4-7.

### question:fixture-reverse

Which indexed types directly depend on the type Fixture.Core.IService?

Subset: control; category: reverse_dependency; depth: 1; expected action: answer.

- Controller has field-use and constructor-use dependencies on IService.
- Service implements IService.

Acceptable source regions: App/Controller.cs:7-8, Core/Service.cs:5-7.

Review note: Type-to-type relationships only; a call to IService.Run targets a method rather than the IService type node.

### question:fixture-cycle

Which two fixture types form a field-dependency cycle?

Subset: primary multi-hop; category: cycle; depth: 2; expected action: answer.

- CycleA has a Peer field of type CycleB.
- CycleB has a Peer field of type CycleA, closing the cycle.

Acceptable source regions: Core/Cycles.cs:3-4.

### question:fixture-unresolved

What source declaration resolves Missing.Call in this indexed fixture?

Subset: control; category: unresolved_reference; depth: 0; expected action: abstain.

- Abstain: supplied evidence cannot establish the requested fact.

Acceptable source regions: none required for abstention.

Review note: Intentionally unresolvable identifier. Expect insufficient evidence, not an invented declaration.

### question:fixture-insufficient

Which database schema stores Controller state in this fixture?

Subset: control; category: insufficient_evidence; depth: 0; expected action: abstain.

- Abstain: supplied evidence cannot establish the requested fact.

Acceptable source regions: none required for abstention.

Review note: Expect abstention from supplied evidence; do not require a claim that PostgreSQL is absent everywhere.

## markovjunior

Source content hash: `sha256:b2534eee221ce2ad219b05235864e77cda3fff0d04e42e9b94dd70b3c9e03db1`

### question:markov-loop

What is the loop condition in Interpreter.Run?

Subset: control; category: local_fact; depth: 0; expected action: answer.

- The loop requires current to be non-null.
- It also requires steps <= 0 or counter < steps; non-positive steps remove the step-count bound.

Acceptable source regions: source/Interpreter.cs:63-78.

### question:markov-initialization

How is execution initialized and when does its main loop stop?
Subset: control; category: local_fact; depth: 0; expected action: answer.

- execution starts when a tree or a set of nodes are defined.
- main loop stops after reaching the last node of the tree or when no more nodes are available(?).

Acceptable source regions: pending revision.

### question:markov-initialization

How does Interpreter.Run initialize its random generator and grid before executing nodes?

Subset: control; category: local_fact; depth: 0; expected action: answer.

- It creates a Random instance using the seed argument.
- It assigns grid = startgrid and clears the grid.
- If origin is true, it sets the central grid cell to 1.

Acceptable source regions: source/Interpreter.cs:52-57.

### question:markov-grid

What does Interpreter.Load call to create the grid, and how does it handle a null grid result?

Subset: control; category: dependency; depth: 1; expected action: answer.

- Interpreter.Load calls Grid.Load with xelem and the MX, MY, MZ dimensions.
- A null grid causes a failure message and a null return.

Acceptable source regions: source/Interpreter.cs:23-33.

### question:markov-static-path

What static call path connects Interpreter.Load to Node.Load?

Subset: primary multi-hop; category: path; depth: 2; expected action: answer.

- Interpreter.Load calls Node.Factory.
- Node.Factory calls result.Load, statically resolved to Node.Load.

Acceptable source regions: source/Interpreter.cs:43-45, source/Node.cs:9-9, source/Node.cs:16-45.

Review note: Used in earlier development smoke tests; this is a calibration question, not held-out evidence. Runtime-override caveats are optional; an invented unique runtime implementation is a separate unsupported claim.

### question:markov-reverse

Which method of Branch directly calls Node.Factory while constructing children?

Subset: control; category: reverse_dependency; depth: 1; expected action: answer.

- Branch.Load calls the inherited static Factory method for each child, resolved to Node.Factory.

Acceptable source regions: source/Node.cs:57-76.

### question:markov-inheritance

How do SequenceNode and MarkovNode reach Node through inheritance?

Subset: primary multi-hop; category: path; depth: 2; expected action: answer.

- SequenceNode inherits Branch.
- MarkovNode inherits Branch.
- Branch inherits Node.

Acceptable source regions: source/Node.cs:51-55, source/Node.cs:99-103.

### question:markov-cycle

What type-dependency cycle connects Node, Interpreter, and Branch using Node.ip, Interpreter.root, and the base class of Branch?

Subset: primary multi-hop; category: cycle; depth: 3; expected action: answer.

- Node has an ip field of type Interpreter.
- Interpreter has a root field of type Branch.
- Branch inherits Node, closing the type-dependency cycle.

Acceptable source regions: source/Node.cs:7-14, source/Node.cs:51-55, source/Interpreter.cs:9-11.

Review note: The cycle needs three relationships, exceeding the graph context single-path depth of two; multiple supplied paths may be needed.

### question:markov-insufficient

Which PostgreSQL schema does MarkovJunior use to store execution state?

Subset: control; category: insufficient_evidence; depth: 0; expected action: abstain.

- Abstain: supplied evidence cannot establish the requested fact.

Acceptable source regions: none required for abstention.

Review note: Used in earlier smoke tests; an abstention check, not a held-out generalization claim.
