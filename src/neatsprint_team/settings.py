from neatsprint_lib.settings import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "team"
    api_prefix: str = "teams"
    bootstrap_token: str | None = None
    outbox_enabled: bool = True
    outbox_stream: str = "neatsprint.events"


settings = Settings()
