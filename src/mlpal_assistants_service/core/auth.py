"""JWT validation for AWS Cognito authentication.

Validates JWT tokens from Cognito for user authentication.
Used alongside API key auth for the /keys endpoint.
"""

import logging
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from mlpal_assistants_service.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class JWTUser:
    """User information extracted from JWT token."""

    cognito_sub: str
    email: str
    first_name: str | None = None
    last_name: str | None = None


class CognitoTokenValidator:
    """Validates AWS Cognito JWT tokens."""

    def __init__(self) -> None:
        settings = get_settings()
        self.region = settings.cognito_region
        self.user_pool_id = settings.cognito_user_pool_id
        self.client_id = settings.cognito_client_id
        self.issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

        # Initialize JWK client to fetch public keys
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._jwk_client: PyJWKClient | None = None

    @property
    def jwk_client(self) -> PyJWKClient:
        """Lazy initialization of JWK client."""
        if self._jwk_client is None:
            self._jwk_client = PyJWKClient(self.jwks_url)
        return self._jwk_client

    def validate_token(self, token: str) -> dict:
        """
        Validate a JWT token from Cognito.

        Args:
            token: JWT token string

        Returns:
            Decoded token claims

        Raises:
            JWTValidationError: If token is invalid
        """
        try:
            # Get the signing key from Cognito's JWKS
            signing_key = self.jwk_client.get_signing_key_from_jwt(token)

            # Decode and validate the token
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": False,  # Cognito doesn't set nbf
                    "verify_iat": True,
                    "verify_aud": False,  # id_token doesn't have aud claim
                    "verify_iss": True,
                },
            )

            # Additional validation for token use
            if claims.get("token_use") not in ["id", "access"]:
                raise JWTValidationError("Invalid token use")

            return claims

        except jwt.ExpiredSignatureError:
            raise JWTValidationError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise JWTValidationError(f"Invalid token: {e}")
        except Exception as e:
            logger.warning(f"JWT validation failed: {e}")
            raise JWTValidationError(f"Token validation failed: {e}")

    def extract_user(self, claims: dict) -> JWTUser:
        """
        Extract user information from token claims.

        Args:
            claims: Decoded JWT claims

        Returns:
            JWTUser with user information
        """
        return JWTUser(
            cognito_sub=claims.get("sub"),
            email=claims.get("email"),
            first_name=claims.get("given_name"),
            last_name=claims.get("family_name"),
        )


class JWTValidationError(Exception):
    """Raised when JWT validation fails."""

    pass


# Singleton validator instance
_validator: CognitoTokenValidator | None = None


def get_cognito_validator() -> CognitoTokenValidator:
    """Get the singleton CognitoTokenValidator instance."""
    global _validator
    if _validator is None:
        _validator = CognitoTokenValidator()
    return _validator
