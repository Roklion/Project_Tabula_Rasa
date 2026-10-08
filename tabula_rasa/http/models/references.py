from .common import DTO
from .mutations import ProtectedMutation


class CategoryChanges(DTO):
    name: str
    kind: str
    parent_id: str | None = None


class Category(CategoryChanges):
    id: str
    baseline: str


class CategoryList(DTO):
    items: list[Category]


class CategoryUpdate(ProtectedMutation):
    changes: CategoryChanges


class ManagedChanges(DTO):
    name: str
    active: bool


class ManagedReference(ManagedChanges):
    id: str
    created_at: str
    baseline: str


class ManagedList(DTO):
    items: list[ManagedReference]


class ManagedUpdate(ProtectedMutation):
    changes: ManagedChanges


class ManagedMerge(DTO):
    source_ids: list[str]
    baselines: dict[str, str]


def category_response(row):
    return Category(id=row['id'], name=row['name'], kind=row['kind'],
                    parent_id=row['parent_id'] or None, baseline=row['baseline'])


def managed_response(row):
    return ManagedReference(id=row['id'], name=row['name'], active=row['active'] in (True, 'TRUE'),
                            created_at=row['created_at'], baseline=row['baseline'])
