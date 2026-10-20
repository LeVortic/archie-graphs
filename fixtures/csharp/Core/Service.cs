namespace Fixture.Core;

public interface IService { void Run(); }
public class BaseService { public virtual void Run() { } }
public class Service : BaseService, IService
{
    public override void Run() { }
}
