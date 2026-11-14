# Development benchmark review packet

Primary focus selected by the project owner: factual correctness on multi-hop C# architecture questions. Both benchmark JSON files record label approval by Victor on 2026-11-10. The questions below mirror those approved files. Formal scoring-protocol approval and held-out validation remain pending. Rosa reviewed the saved answers on 2026-11-11; see [answer review](ANSWER_REVIEW.md).

## Research question

Does source-backed dependency-graph context improve factual correctness on multi-hop C# architecture questions, compared with source-only retrieval using the same local model and context ceiling?

## Proposed operational measure

Primary subset: questions annotated dependency_depth >= 2. Proposed primary metric: macro-average human-annotated atomic-fact F1 on that subset, with precision and recall reported separately. See PROTOCOL.md for the review procedure and edge cases. This scoring definition is proposed, not yet approved.

The packet contains 29 questions. Sixteen development questions (five primary multi-hop, eleven controls) were written by the project owner; some were used during development, so do not report them as held-out evidence. Thirteen further questions (IDs containing `-rc-`; three primary multi-hop, ten controls) were added by a second reviewer, Rosa Cortes, who did not take part in development; they were drafted with Claude, manually verified against the source and not used to tune retrieval, graph selection or prompts. This is still not a sufficient held-out research dataset.

## Remaining research review

1. Confirm or revise research-question wording and the proposed fact-F1 measure.
2. Check each expected fact against its cited source; split compound facts and remove unasked requirements.
3. Check dependency depth, category, acceptable citations, and abstention cases.
4. Keep abstention labels about insufficient evidence rather than proving repository-wide absence.
5. Report corrections and reviewer name/date. Keep benchmark-label approval separate from answer grading and formal research-protocol approval.

Passing structural citation checks does not establish factual correctness or relevance. MarkovJunior has no verified upstream commit in this local snapshot; its indexed content hash is recorded instead. Actual token usage can differ between modes and must be reported; equal ceilings alone do not isolate a causal graph benefit.

## fixture

Source content hash: `sha256:450aba2d1f8f30230a7cda5eda6481632adabd6b9ca0515db80eadaccd4a1f7d`

### question:fixture-interface

Which interface does Fixture.Core.Service implement?

Category: local_fact; depth: 0; expected action: answer.

- Fixture.Core.Service implements Fixture.Core.IService.

Acceptable source regions: Core/Service.cs:3-7.

### question:fixture-injection

What does Fixture.App.Controller receive in its constructor and store in its service field?

Category: dependency; depth: 1; expected action: answer.

- Controller receives an IService constructor parameter.
- The service field has declared type IService.

Acceptable source regions: App/Controller.cs:7-8.

### question:fixture-call

What is the target of the call in Fixture.App.Controller.Handle?

Category: dependency; depth: 1; expected action: answer.

- Controller.Handle calls the declared IService.Run method.

Acceptable source regions: App/Controller.cs:9-9, Core/Service.cs:3-7.

Review note: Do not require an unasked runtime caveat for full fact recall; any definite runtime-implementation claim must be checked separately.

### question:fixture-base-path

What connects Fixture.App.Controller to Fixture.Core.BaseService?

Category: path; depth: 2; expected action: answer.

- Controller creates Service instances, giving an extracted constructor-use dependency on Service.
- Service inherits BaseService, giving the path Controller to Service to BaseService.

Acceptable source regions: App/Controller.cs:10-11, Core/Service.cs:4-7.

### question:fixture-reverse

Which types directly depend on Fixture.Core.IService, and through which relationships?

Category: reverse_dependency; depth: 1; expected action: answer.

- Controller has field-use and constructor-use dependencies on IService.
- Service implements IService.

Acceptable source regions: App/Controller.cs:7-8, Core/Service.cs:5-7.

Review note: Type-to-type relationships only; a call to IService.Run targets a method rather than the IService type node.

### question:fixture-cycle

Which two fixture types form a field-dependency cycle?

Category: cycle; depth: 2; expected action: answer.

- CycleA has a Peer field of type CycleB.
- CycleB has a Peer field of type CycleA, closing the cycle.

Acceptable source regions: Core/Cycles.cs:3-4.

### question:fixture-unresolved

What source declaration resolves Missing.Call in this indexed fixture?

Category: unresolved_reference; depth: 0; expected action: abstain.

No expected facts; insufficient evidence expected.

Acceptable source regions: None; insufficient evidence expected.

Review note: Intentionally unresolvable identifier. Expect insufficient evidence, not an invented declaration.

### question:fixture-insufficient

Which database schema stores Controller state in this fixture?

Category: insufficient_evidence; depth: 0; expected action: abstain.

No expected facts; insufficient evidence expected.

Acceptable source regions: None; insufficient evidence expected.

Review note: Expect abstention from supplied evidence; do not require a claim that PostgreSQL is absent everywhere.

### question:fixture-rc-run-declarations

Which types in Fixture.Core declare a Run method, and how?

Subset: control; category: local_fact; depth: 0; expected action: answer.

How is execution initialized and when does its main loop stop?
- IService declares Run as an interface method.
- BaseService declares Run as virtual.
- Service overrides Run.

Category: local_fact; depth: 0; expected action: answer.
Acceptable source regions: Core/Service.cs:3-7.

- Execution is initialized by setting the root node, it requires current to be non-null.
- in the while loop: while (current != null && (steps <= 0 || counter < steps))
Review note: Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

Acceptable source regions: source/Interpreter.cs:60-78.
### question:fixture-rc-service-dependents

Review note: Mentioning loop makes the LLM focus both answers on it, rather than look for the execution of the whole program
Which types directly depend on Fixture.Core.Service, and through which relationships?

Subset: control; category: reverse_dependency; depth: 1; expected action: answer.

- Controller depends on Service through constructor use in Create (new Service()).
- Controller also creates a Service with target-typed new() in CreateImplicit.

Acceptable source regions: App/Controller.cs:10-11.

Review note: Return types are not extracted relationships. Reverse question: graph evidence currently follows outgoing relationships only. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:fixture-rc-insufficient

Which logging library does Fixture.App use?

Subset: control; category: insufficient_evidence; depth: 0; expected action: abstain.

- Abstain: supplied evidence cannot establish the requested fact.

Acceptable source regions: none required for abstention.

Review note: Expect abstention from supplied evidence; do not require a claim that logging is absent everywhere. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

## markovjunior

Source content hash: `sha256:b2534eee221ce2ad219b05235864e77cda3fff0d04e42e9b94dd70b3c9e03db1`

### question:markov-loop

How is execution initialized and when does its main loop stop?

Subset: control; category: local_fact; depth: 0; expected action: answer.

- Execution is initialized by setting the root node, it requires current to be non-null.
- in the while loop: while (current != null && (steps <= 0 || counter < steps))

Acceptable source regions: source/Interpreter.cs:60-78.

Review note: Mentioning loop makes the LLM focus both answers on it, rather than look for the execution of the whole program

### question:markov-initialization

How does Interpreter.Run initialize its random generator and grid before executing nodes?

Category: local_fact; depth: 0; expected action: answer.

- It creates a Random instance using the seed argument.
- It assigns grid = startgrid and clears the grid.
- If origin is true, it sets the central grid cell to 1.

Acceptable source regions: source/Interpreter.cs:52-57.

### question:markov-grid

What does Interpreter.Load call to create the grid, and how does it handle a null grid result?

Category: dependency; depth: 1; expected action: answer.

- Interpreter.Load calls Grid.Load with xelem and the MX, MY, MZ dimensions.
- A null grid causes a failure message and a null return.

Acceptable source regions: source/Interpreter.cs:23-44.

### question:markov-static-path

What static call path connects Interpreter.Load to Node.Load?

Category: path; depth: 2; expected action: answer.

- Interpreter.Load calls Node.Factory.
- Node.Factory calls result.Load, statically resolved to Node.Load.

Acceptable source regions: source/Interpreter.cs:43-45, source/Node.cs:9-9, source/Node.cs:16-45.

Review note: Used in earlier development smoke tests; this is a calibration question, not held-out evidence. Runtime-override caveats are optional; an invented unique runtime implementation is a separate unsupported claim.

### question:markov-reverse

Which method of Branch directly calls Node.Factory while constructing children?

Category: reverse_dependency; depth: 1; expected action: answer.

- Branch.Load calls the inherited static Factory method for each child, resolved to Node.Factory.

Acceptable source regions: source/Node.cs:57-76.

### question:markov-inheritance

How do SequenceNode and MarkovNode reach Node?

Category: path; depth: 2; expected action: answer.

- SequenceNode inherits Branch.
- MarkovNode inherits Branch.
- Branch inherits Node.

Acceptable source regions: source/Node.cs:51-55, source/Node.cs:99-103.

### question:markov-cycle

What type-dependency cycle connects Node, Interpreter, and Branch?

Category: cycle; depth: 3; expected action: answer.

- Node has an ip field of type Interpreter.
- Interpreter has a root field of type Branch.
- Branch inherits Node, closing the type-dependency cycle.

Acceptable source regions: source/Node.cs:7-14, source/Node.cs:51-55, source/Interpreter.cs:9-11.

Review note: The cycle needs three relationships, exceeding the graph context single-path depth of two; multiple supplied paths may be needed.

### question:markov-insufficient

Which database schema does MarkovJunior use to store execution state?

Category: insufficient_evidence; depth: 0; expected action: abstain.

No expected facts; insufficient evidence expected.

Acceptable source regions: None; insufficient evidence expected.

Review note: Used in earlier smoke tests; an abstention check, not a held-out generalization claim.

### question:markov-rc-overlap-path

How does OverlapNode reach Node?

Subset: primary multi-hop; category: path; depth: 3; expected action: answer.

- OverlapNode inherits WFCNode.
- WFCNode inherits Branch.
- Branch inherits Node.

Acceptable source regions: source/OverlapModel.cs:8-8, source/WaveFunctionCollapse.cs:7-7, source/Node.cs:51-51.

Review note: Needs three inheritance relationships, which exceeds the graph context single-path depth of two; multiple supplied paths may be needed. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-rulenode-subclasses

Which classes inherit directly from RuleNode?

Subset: control; category: reverse_dependency; depth: 1; expected action: answer.

- OneNode inherits RuleNode.
- AllNode inherits RuleNode.
- ParallelNode inherits RuleNode.

Acceptable source regions: source/OneNode.cs:7-7, source/AllNode.cs:8-8, source/ParallelNode.cs:5-5.

Review note: Reverse question: graph evidence currently follows outgoing relationships only, so answers may rely on source excerpts. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-main-grid-path

What static call path connects Program.Main to Grid.Load?

Subset: primary multi-hop; category: path; depth: 2; expected action: answer.

- Program.Main calls Interpreter.Load.
- Interpreter.Load calls Grid.Load.

Acceptable source regions: source/Program.cs:40-40, source/Interpreter.cs:27-27.

Review note: Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-run-go-path

What static call path connects Interpreter.Run to Node.Go?

Subset: primary multi-hop; category: path; depth: 2; expected action: answer.

- Interpreter.Run calls Branch.Go through current.Go().
- Branch.Go calls Node.Go through node.Go() on each child node.

Acceptable source regions: source/Interpreter.cs:9-9, source/Interpreter.cs:76-76, source/Node.cs:51-51, source/Node.cs:79-85.

Review note: Static symbol resolution; runtime overrides such as RuleNode.Go are not required facts. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-search-caller

Which method calls Search.Run, and when?

Subset: control; category: reverse_dependency; depth: 1; expected action: answer.

- RuleNode.Go calls Search.Run.
- Search.Run is called only when observations is not null, futureComputed is false, ComputeFutureSetPresent returns true, and the search flag is enabled.

Acceptable source regions: source/RuleNode.cs:124-141.

Review note: Reverse question: graph evidence currently follows outgoing relationships only. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-branch-self

Which class has a field whose type is the same class?

Subset: control; category: cycle; depth: 1; expected action: answer.

- Branch has a field named parent of type Branch.

Acceptable source regions: source/Node.cs:53-53.

Review note: A self-loop field_use relationship. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-wfc-factory

Which node classes does Node.Factory create for a wfc element?

Subset: control; category: local_fact; depth: 0; expected action: answer.

- With a sample attribute it creates an OverlapNode.
- With a tileset attribute it creates a TileNode.

Acceptable source regions: source/Node.cs:35-36.

Review note: Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-rulenode-loads

Which helper objects does RuleNode create while loading field and observe elements?

Subset: control; category: dependency; depth: 1; expected action: answer.

- It creates a Field for each field element.
- It creates an Observation for each observe element.

Acceptable source regions: source/RuleNode.cs:65-72, source/RuleNode.cs:82-89.

Review note: RuleNode stores them in array fields (Field[], Observation[]); array field types are not extracted, but the constructor_use relationships are. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-output

How does Program.Main save each result?

Subset: control; category: dependency; depth: 1; expected action: answer.

- For 2D results (FZ == 1) or when iso is set, it renders with Graphics.Render and saves a PNG with Graphics.SaveBitmap.
- Otherwise it saves a VOX file with VoxHelper.SaveVox.

Acceptable source regions: source/Program.cs:67-73.

Review note: Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.

### question:markov-rc-insufficient

Which HTTP endpoint does MarkovJunior use to download its models?

Subset: control; category: insufficient_evidence; depth: 0; expected action: abstain.

- Abstain: supplied evidence cannot establish the requested fact.

Acceptable source regions: none required for abstention.

Review note: Expect abstention. Stating that the excerpts show models loaded from local XML files is acceptable; an invented endpoint is not. Added by Rosa Cortes on 2026-11-14; drafted with Claude and manually verified against the source; not used during development.
