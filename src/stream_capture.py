from __future__ import annotations

import argparse
import asyncio
import datetime
import gc
from collections.abc import AsyncGenerator
from typing import TypedDict

import cv2
import numpy as np
import speedtest
import streamlink


class InputData(TypedDict):
    stream_url: str
    capture_interval: int


class ResultData(TypedDict):
    frame: np.ndarray
    timestamp: float


class StreamCapture:
    """
    A class to capture frames from a video stream.
    """

    def __init__(self, stream_url: str, capture_interval: int = 15):
        """
        Initialises the StreamCapture with the given stream URL.

        Args:
            stream_url (str): The URL of the video stream.
            capture_interval (int, optional): The interval at which frames
                should be captured. Defaults to 15.
        """
        # Video stream URL
        self.stream_url = stream_url
        # Video capture object
        self.cap: cv2.VideoCapture | None = None
        # Frame capture interval in seconds
        self.capture_interval = capture_interval
        # Flag to indicate successful capture
        self.successfully_captured = False

    async def initialise_stream(self, stream_url: str) -> None:
        """
        Initialises the video stream.

        Args:
            stream_url (str): The URL of the stream to initialise.
        """
        self.cap = cv2.VideoCapture(stream_url)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'H264'))

        if not self.cap.isOpened():
            await asyncio.sleep(5)
            self.cap.open(stream_url)

    async def release_resources(self) -> None:
        """
        Releases resources like the capture object.
        """
        if self.cap:
            self.cap.release()
            self.cap = None
        gc.collect()

    async def execute_capture(
        self,
    ) -> AsyncGenerator[tuple[np.ndarray, float]]:
        """
        Captures frames from the stream and yields them with timestamps.

        Yields:
            Tuple[np.ndarray, float]: The captured frame and the timestamp.
        """
        await self.initialise_stream(self.stream_url)
        last_process_time = datetime.datetime.now() - datetime.timedelta(
            seconds=self.capture_interval,
        )
        fail_count = 0  # Counter for consecutive failures

        while True:
            if self.cap is None:
                await self.initialise_stream(self.stream_url)

            ret, frame = (
                self.cap.read() if self.cap is not None else (False, None)
            )

            if not ret or frame is None:
                fail_count += 1
                print(
                    'Failed to read frame, trying to reinitialise stream. '
                    f"Fail count: {fail_count}",
                )
                await self.release_resources()
                await self.initialise_stream(self.stream_url)
                # Switch to generic frame capture after 5 consecutive failures
                if fail_count >= 5 and not self.successfully_captured:
                    print('Switching to generic frame capture method.')
                    async for generic_frame, timestamp in (
                        self.capture_generic_frames()
                    ):
                        yield generic_frame, timestamp
                    return
                continue
            else:
                # Reset fail count on successful read
                fail_count = 0

                # Mark as successfully captured
                self.successfully_captured = True

            # Process the frame if the capture interval has elapsed
            current_time = datetime.datetime.now()
            elapsed_time = (current_time - last_process_time).total_seconds()

            # If the capture interval has elapsed, yield the frame
            if elapsed_time >= self.capture_interval:
                last_process_time = current_time
                timestamp = current_time.timestamp()
                yield frame, timestamp

                # Clear memory
                del frame, timestamp
                gc.collect()

            await asyncio.sleep(0.01)  # Adjust the sleep time as needed

        await self.release_resources()

    def check_internet_speed(self) -> tuple[float, float]:
        """
        Checks internet speed using the Speedtest library.

        Returns:
            Tuple[float, float]: Download and upload speeds (Mbps).
        """
        st = speedtest.Speedtest()
        st.get_best_server()
        download_speed = st.download() / 1_000_000  # Turn into Mbps
        upload_speed = st.upload() / 1_000_000
        return download_speed, upload_speed

    def select_quality_based_on_speed(self) -> str | None:
        """
        Selects stream quality based on internet speed.

        Returns:
            str: The URL of the selected stream quality.

        Raises:
            Exception: If compatible stream quality is not available.
        """
        download_speed, _ = self.check_internet_speed()
        try:
            streams = streamlink.streams(self.stream_url)
            available_qualities = list(streams.keys())
            print(f"Available qualities: {available_qualities}")

            if download_speed > 10:
                preferred_qualities = [
                    'best',
                    '1080p',
                    '720p',
                    '480p',
                    '360p',
                    '240p',
                    'worst',
                ]
            elif 5 < download_speed <= 10:
                preferred_qualities = ['720p', '480p', '360p', '240p', 'worst']
            else:
                preferred_qualities = ['480p', '360p', '240p', 'worst']

            for quality in preferred_qualities:
                if quality in available_qualities:
                    selected_stream = streams[quality]
                    print(f"Selected quality based on speed: {quality}")
                    return selected_stream.url

            raise Exception('No compatible stream quality is available.')
        except Exception as e:
            print(f"Error selecting quality based on speed: {e}")
            return None

    async def capture_generic_frames(
        self,
    ) -> AsyncGenerator[tuple[np.ndarray, float]]:
        """
        Captures frames from a generic stream.

        Yields:
            Tuple[np.ndarray, float]: The captured frame and the timestamp.
        """
        # Select the stream quality based on internet speed
        stream_url = self.select_quality_based_on_speed()
        if not stream_url:
            print('Failed to get suitable stream quality.')
            return

        # Initialise the stream with the selected URL
        await self.initialise_stream(stream_url)

        last_process_time = datetime.datetime.now()
        fail_count = 0  # Counter for consecutive failures

        while True:
            # Read the frame from the stream
            ret, frame = (
                self.cap.read() if self.cap is not None else (False, None)
            )

            # Handle failed frame reads
            if not ret or frame is None:
                fail_count += 1
                print(
                    'Failed to read frame from generic stream. '
                    f"Fail count: {fail_count}",
                )

                # Reinitialise the stream after 5 consecutive failures
                if fail_count >= 5 and not self.successfully_captured:
                    print('Reinitialising the generic stream.')
                    await self.release_resources()
                    await asyncio.sleep(5)
                    stream_url = self.select_quality_based_on_speed()

                    # Exit if no suitable stream quality is available
                    if not stream_url:
                        print('Failed to get suitable stream quality.')
                        continue

                    # Reinitialise the stream with the new URL
                    await self.initialise_stream(stream_url)
                    fail_count = 0
                continue
            else:
                # Reset fail count on successful read
                fail_count = 0

                # Mark as successfully captured
                self.successfully_captured = True

            current_time = datetime.datetime.now()
            elapsed_time = (current_time - last_process_time).total_seconds()

            if elapsed_time >= self.capture_interval:
                last_process_time = current_time
                timestamp = current_time.timestamp()
                yield frame, timestamp

                # Clear memory
                del frame, timestamp
                gc.collect()

            await asyncio.sleep(0.01)  # Adjust the sleep time as needed

    def update_capture_interval(self, new_interval: int) -> None:
        """
        Updates the capture interval.

        Args:
            new_interval (int): Frame capture interval in seconds.
        """
        self.capture_interval = new_interval


async def main():
    parser = argparse.ArgumentParser(
        description='Capture video stream frames asynchronously.',
    )
    parser.add_argument(
        '--url',
        type=str,
        help='Live stream URL',
        required=True,
    )
    args = parser.parse_args()

    stream_capture = StreamCapture(args.url)
    async for frame, timestamp in stream_capture.execute_capture():
        # Process the frame here
        print(f"Frame at {timestamp} displayed")
        # Release the frame resources
        del frame
        gc.collect()


if __name__ == '__main__':
    asyncio.run(main())
