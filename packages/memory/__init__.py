__all__ = ["ProjectMemoryService"]


def __getattr__(name: str):
    if name == "ProjectMemoryService":
        from packages.memory.project_memory import ProjectMemoryService

        return ProjectMemoryService
    raise AttributeError(name)
