from pydantic.generics import GenericModel
from typing import TypeVar, Generic

T = TypeVar("T")

class DataWrapper(GenericModel, Generic[T]):
    data: T

class ResponseWrapper(GenericModel, Generic[T]):
    data: T
