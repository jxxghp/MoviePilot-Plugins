from typing import TypeVar, Generic, Iterator, Any
from pydantic import BaseModel, RootModel, Field, model_validator
from .metadata import Metadata


# Specific data payload model
T = TypeVar("T")

class ResourceItem(BaseModel, Generic[T]):
    """Generic resource item model"""
    name: str = Field(..., description="Resource name")
    data: T = Field(..., description="Resource data payload")
    meta: Metadata = Field(default_factory=Metadata, description="Resource metadata")


# Subclasses of ResourceItem
R = TypeVar("R", bound=ResourceItem)

class ResourceList(RootModel[list[R]], Generic[R]):
    """
    Generic configuration list base class
    """
    root: list[R] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_unique_names(self) -> 'ResourceList[R]':
        names = [item.name for item in self.root]
        if len(names) != len(set(names)):
            raise ValueError("names must be unique")
        return self

    def __iter__(self) -> Iterator[R]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def __contains__(self, name: str) -> bool:
        """Check if a configuration with the specified name exists"""
        return any(item.name == name for item in self.root)

    def get(self, name: str) -> R | None:
        """Get the configuration item by name"""
        for item in self.root:
            if item.name == name:
                return item
        return None

    def add(self, item: R):
        """Add a configuration item, raise an exception if the name is duplicated"""
        if item.name in self:
            raise ValueError(f"name {item.name!r} already exists")
        self.root.insert(0, item)

    def remove(self, name: str):
        """Remove the configuration item by name"""
        self.root = [item for item in self.root if item.name != name]

    def pop(self, name: str) -> R | None:
        """Remove and return the configuration item with the specified name"""
        for i, item in enumerate(self.root) :
            if item.name == name:
                return self.root.pop(i)
        return None

    def update(self, name: str, item: R):
        """Update the configuration item with the specified name"""
        for i, existing_item in enumerate(self.root):
            if existing_item.name == name:
                item.meta = self.root[i].meta
                self.root[i] = item
                return

    def update_data(self, name: str, data: Any) -> bool:
        """Update only the data payload of the configuration item with the specified name"""
        item = self.get(name)
        if item:
            item.data = data
            return True
        return False

    def set_meta(self, name: str, meta: Metadata) -> bool:
        """Set metadata for the specified configuration item"""
        item = self.get(name)
        if item:
            item.meta = meta
            return True
        return False

    @property
    def names(self) -> list[str]:
        """Return a list of names for all configuration items"""
        return [item.name for item in self.root]
