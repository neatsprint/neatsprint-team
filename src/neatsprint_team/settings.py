from neatsprint_lib.settings import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "team"
    api_prefix: str = "teams"


settings = Settings()
