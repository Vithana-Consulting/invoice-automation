from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class LeafCondition(BaseModel):
    field: str
    op: str
    value: Any = None


class GroupCondition(BaseModel):
    operator: Literal["AND", "OR"]
    conditions: List[Union[LeafCondition, "GroupCondition"]] = Field(min_length=1)


# Allow recursive references
GroupCondition.model_rebuild()

ConditionTree = Union[LeafCondition, GroupCondition]


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    priority: int = 0
    is_active: bool = True
    conditions: ConditionTree
    action_type: str = "set_push_to"
    action_value: str = Field(min_length=1, max_length=255)


class RuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    conditions: Optional[ConditionTree] = None
    action_type: Optional[str] = None
    action_value: Optional[str] = None


class RuleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    priority: int
    is_active: bool
    conditions: Any
    action_type: str
    action_value: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class RuleReorder(BaseModel):
    rule_ids: List[int] = Field(min_length=1)


class RuleEvaluateRequest(BaseModel):
    invoice_fields: dict
