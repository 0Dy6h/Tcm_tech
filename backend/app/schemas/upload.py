from pydantic import BaseModel, Field


class StoredUpload(BaseModel):
    literature_id: str = Field(min_length=1)
    pdf_upload_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    file_size: int = Field(ge=0)
    storage_path: str = Field(min_length=1)
    pdf_parse_status: str = Field(min_length=1)


class FakePdfAutoParseRequest(BaseModel):
    literature_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    pdf_upload_id: str | None = Field(default=None, min_length=1, max_length=104)
