from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

from src.utils import TokenManager

# Load environment variables
load_dotenv()


class ViolationSender:
    """
    Responsible for sending violation images and metadata to the backend API.
    Handles authentication, token refresh, and retry logic for robust delivery.
    """

    def __init__(
        self,
        api_url: str | None = None,
        max_retries: int = 3,
        timeout: int = 10,
    ) -> None:
        """
        Initialise the ViolationSender.

        Args:
            api_url (str | None): The base URL for the violation API endpoint.
                If None, uses environment variable.
            max_retries (int): Maximum number of retry attempts for requests.
            timeout (int): Timeout for HTTP requests in seconds.
        """
        # Load API URL from environment variable if not provided
        if api_url is None:
            api_url = os.getenv(
                'VIOLATION_RECORD_API_URL',
                'http://127.0.0.1:8002',
            )

        self.base_url: str = api_url.rstrip('/')
        self.shared_token: dict[str, str | bool] = {
            'access_token': '',
            'refresh_token': '',
            'is_refreshing': False,
        }
        self.max_retries: int = max_retries
        self.timeout: int = timeout

        # Use a shared client connection pool
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

        logging.getLogger('httpx').setLevel(logging.WARNING)

        self.token_manager: TokenManager = TokenManager(
            shared_token=self.shared_token,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Get an HTTP client with connection pooling.

        Returns:
            httpx.AsyncClient: 異步 HTTP 客戶端
        """
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    limits=httpx.Limits(
                        max_keepalive_connections=5,
                        max_connections=10,
                        keepalive_expiry=30,
                    ),
                    http2=True,  # Enable HTTP/2 for improved performance
                )
            return self._client

    async def close(self) -> None:
        """
        Close the HTTP client connection pool if it exists.
        """
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
                self._client = None

    async def send_violation(
        self,
        site: str,
        stream_name: str,
        image_bytes: bytes,
        detection_time: datetime | None = None,
        warnings_json: str | None = None,
        detections_json: str | None = None,
        cone_polygon_json: str | None = None,
        pole_polygon_json: str | None = None,
    ) -> str | None:
        """
        Send a violation image and associated metadata to the backend API.

        Args:
            site (str): The site label.
            stream_name (str): The stream identifier.
            image_bytes (bytes): The image data in bytes.
            detection_time (Optional[datetime]): The time of detection.
            warnings_json (Optional[str]): JSON string of warnings.
            detections_json (Optional[str]): JSON string of detection items.
            cone_polygon_json (Optional[str]): JSON string of cone polygons.
            pole_polygon_json (Optional[str]): JSON string of pole polygons.

        Returns:
            Optional[str]:
                The violation ID (string) if successful,
                or None if all attempts fail.

        Raises:
            RuntimeError:
                If all retry attempts are exhausted or a critical error occurs.
        """
        # Ensure authentication before sending
        access_token = await self.token_manager.get_valid_token()
        if not access_token:
            raise RuntimeError('Failed to obtain valid access token')

        headers: dict[str, str] = {
            'Authorization': f"Bearer {access_token}",
        }

        # Optimise image format - use JPEG to reduce file size
        files: dict[str, tuple[str, bytes, str]] = {
            'image': ('violation.jpg', image_bytes, 'image/jpeg'),
        }

        data: dict[str, str] = {
            'site': site,
            'stream_name': stream_name,
        }
        if detection_time:
            data['detection_time'] = detection_time.isoformat()
        if warnings_json:
            data['warnings_json'] = warnings_json
        if detections_json:
            data['detections_json'] = detections_json
        if cone_polygon_json:
            data['cone_polygon_json'] = cone_polygon_json
        if pole_polygon_json:
            data['pole_polygon_json'] = pole_polygon_json

        upload_url: str = self.base_url + '/upload'

        # Use shared client connection pool
        client = await self._get_client()

        # Exponential backoff retry strategy
        backoff_delay = 1

        # Attempt to send the violation data with retries
        for attempt in range(self.max_retries):
            try:
                resp = await client.post(
                    upload_url,
                    data=data,
                    files=files,
                    headers=headers,
                )
                resp.raise_for_status()
                # Return the violation ID from the response
                return resp.json().get('violation_id')

            except httpx.ConnectTimeout:
                logging.warning(
                    f"[send_violation] Attempt {attempt+1}: "
                    'Connection timeout, retry...',
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2  # Exponential backoff
                else:
                    raise RuntimeError(
                        '[send_violation] All retry attempts exhausted due to '
                        'timeout',
                    )

            except httpx.HTTPStatusError as exc:
                # If 401, refresh token and retry
                if exc.response.status_code == 401:
                    logging.warning(
                        '[send_violation] Unauthorized. '
                        'Attempting token refresh...',
                    )
                    await self.token_manager.refresh_token()
                    # Update headers with new token
                    new_token = await self.token_manager.get_valid_token()
                    headers['Authorization'] = f"Bearer {new_token}"

                    if attempt < self.max_retries - 1:
                        continue  # Retry instead of recursive call
                raise

            except Exception as e:
                logging.error(f"[send_violation] Unexpected error: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2
                else:
                    raise

        # If all attempts fail, return None
        return None
