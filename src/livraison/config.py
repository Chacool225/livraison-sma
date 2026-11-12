"""Configuration de l'application, lue depuis le fichier .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "livraison"
    postgres_password: str = "changez-moi"
    postgres_db: str = "livraison"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_url: str = "redis://localhost:6379/0"

    xmpp_host: str = "localhost"
    xmpp_port: int = 5222
    xmpp_domaine: str = "localhost"
    xmpp_mot_de_passe_agents: str = "changez-moi"

    osrm_url: str = "http://localhost:5000"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    jwt_secret: str = "changez-moi"
    jwt_duree_heures: int = 12

    # "dev" : le code SMS est renvoyé dans la réponse de l'API (pas de vrai SMS).
    # Toute autre valeur : le code n'est jamais renvoyé et les secrets par défaut sont refusés.
    environnement: str = "dev"
    code_validite_minutes: int = 5
    code_tentatives_max: int = 5
    codes_max_par_10_min: int = 5
    indicatif_pays_defaut: str = "+225"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def jid(self, nom: str) -> str:
        """Identifiant XMPP d'un agent, par exemple dispatcher@localhost."""
        return f"{nom}@{self.xmpp_domaine}"


parametres = Parametres()
