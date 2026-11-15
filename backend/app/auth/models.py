from typing import Optional
from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    id: str
    name: str
    email: str
    email_verified: bool = False
    image: Optional[str] = None
    session_id: str
    token: str
