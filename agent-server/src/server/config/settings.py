from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    port_backend: int
    port_agentserver: int
    llm_api_key: str

    model_config = SettingsConfigDict(
        env_file = "../.env",
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

settings = Settings()