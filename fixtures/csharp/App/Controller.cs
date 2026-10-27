using Fixture.Core;

namespace Fixture.App;

public class Controller
{
    private readonly IService service;
    public Controller(IService service) { this.service = service; }
    public void Handle() { service.Run(); }
    public Service Create() => new Service();
    public Service CreateImplicit() => new();
}
