namespace Fixture.Core;

public class CycleA { public CycleB Peer; }
public class CycleB { public CycleA Peer; }
