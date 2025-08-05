from pydantic import BaseModel
from typing import TypeVar, Generic

T = TypeVar("T")

class DataWrapper(BaseModel, Generic[T]):
    data: T

class ResponseWrapper(BaseModel, Generic[T]):
    data: T