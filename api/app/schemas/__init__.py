"""Pydantic v2 схемы для API."""
from app.schemas.admin import AuthRequest, AuthResponse
from app.schemas.collection import (
    CollectionConfigUpdate,
    CollectionInfo,
    CollectionListResponse,
    CreateCollectionRequest,
    DatabaseInfo,
    DatabasesResponse,
)
from app.schemas.feedback import CopyEventIn, DislikeEventIn, FeedbackOut
from app.schemas.hierarchy import (
    HierarchyChildrenResponse,
    HierarchyNode,
    HierarchyResponse,
    HierarchySearchRequest,
    HierarchySearchResponse,
)
from app.schemas.import_export import (
    ImportRequest,
    ImportResponse,
    JobInfo,
    JobListResponse,
    UploadExcelResponse,
)
from app.schemas.material import (
    BatchDeleteRequest,
    BatchUpdateItem,
    BatchUpdateRequest,
    CandidateResult,
    MatchRequest,
    MatchResponse,
    MaterialInfo,
    UpdateCellRequest,
    UpdatePointResponse,
    UpdateRequest,
)
from app.schemas.search import (
    FilterPath,
    MatchResponsePublic,
)
from app.schemas.settings import (
    ApiProviderOut,
    ApiProviderUpdate,
    CleaningRuleOut,
    CleaningRuleUpdate,
    StatusConfig,
    StatusConfigOut,
    StatusesUpdateRequest,
)

__all__ = [
    "ApiProviderOut",
    "ApiProviderUpdate",
    "AuthRequest",
    "AuthResponse",
    "BatchDeleteRequest",
    "BatchUpdateItem",
    "BatchUpdateRequest",
    "CandidateResult",
    "CleaningRuleOut",
    "CleaningRuleUpdate",
    "CollectionConfigUpdate",
    "CollectionInfo",
    "CollectionListResponse",
    "CopyEventIn",
    "CreateCollectionRequest",
    "DatabaseInfo",
    "DatabasesResponse",
    "DislikeEventIn",
    "FeedbackOut",
    "FilterPath",
    "HierarchyChildrenResponse",
    "HierarchyNode",
    "HierarchyResponse",
    "HierarchySearchRequest",
    "HierarchySearchResponse",
    "ImportRequest",
    "ImportResponse",
    "JobInfo",
    "JobListResponse",
    "MatchRequest",
    "MatchResponse",
    "MatchResponsePublic",
    "MaterialInfo",
    "StatusConfig",
    "StatusConfigOut",
    "StatusesUpdateRequest",
    "UpdateCellRequest",
    "UpdatePointResponse",
    "UpdateRequest",
    "UploadExcelResponse",
]
