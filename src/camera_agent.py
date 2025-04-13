import asyncio
import base64
import re
from time import time

import aiofiles
import cv2
from aiohttp import web
from spade import agent, behaviour
from spade.message import Message


class CameraAgent(agent.Agent):
    def __init__(self, jid, password, http_port=3001):
        super().__init__(jid, password)
        # picture requests logging
        # as per default 500ms timeout
        self.timeout = 500  # ms
        self.ban_timeout = 10000  # ms
        self.requests: dict = {}
        self.http_port = http_port
        self.app = web.Application()
        self.app.add_routes(
            [
                web.post("/ban", self.handle_ban_request),
                web.get("/status", self.handle_status),
            ]
        )
        self.runner = None
        self.site = None

        # create event for ban concurrency
        # issues as request is ongoing process
        self.processing_complete = asyncio.Event()
        self.processing_complete.set()

    async def handle_ban_request(self, request):
        """Handle incoming ban requests via HTTP."""
        try:
            # Parse the request body
            data = await request.json()
            if not data or "agent" not in data:
                return web.json_response(
                    {"error": "Invalid request format"}, status=400
                )

            target_jid = data["agent"]
            now = time()

            reset_ban_timeout = lambda last: (
                lambda now: int(round((now - last) * 1000)) >= self.ban_timeout
            )
            # Apply the ban if there is
            # no registred behaviour
            await self.processing_complete.wait()
            self.requests[target_jid] = reset_ban_timeout(now)

            print(
                f"Agent {target_jid} has been banned for {self.ban_timeout}ms"
            )

            return web.json_response(
                {
                    "status": "success",
                    "message": f"Agent {target_jid} has been banned for {self.ban_timeout}ms",
                }
            )

        except Exception as e:
            print(f"Error processing ban request: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_status(self, request):
        """Return status information about the camera agent."""
        return web.json_response(
            {
                "status": "online",
                "jid": str(self.jid),
                "banned_agents": len(self.requests),
            }
        )

    async def start_http_server(self):
        """Start the HTTP server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.http_port)
        await self.site.start()
        print(f"HTTP server started on port {self.http_port}")

    async def stop_http_server(self):
        """Stop the HTTP server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        print("HTTP server stopped")

    class SendPhotoBehaviour(behaviour.OneShotBehaviour):
        def __init__(self, requester_jid, camera):
            super().__init__()
            self.raw_requester_jid = requester_jid
            self.requester_jid = re.sub(r"(.*@.*)\/.*", r"\1", requester_jid)
            self.camera = camera
            self.reset_timeout = lambda last: (
                lambda now: int(round((now - last) * 1000))
                >= self.camera.timeout
            )

        async def run(self):
            self.camera.processing_complete.clear()
            now = time()

            # check if last request exceeded
            # predefined timeout
            if not self.camera.requests.get(self.requester_jid, lambda _: True)(
                now
            ):
                print(
                    f"Request from {self.requester_jid} under timeout. No response.."
                )

                msg = Message(to=self.raw_requester_jid)
                msg.set_metadata("performative", "info")
                msg.body = "Request cancelled due to ban"

                await self.send(msg)

            print("Capturing image...")
            camera = cv2.VideoCapture(2)

            await asyncio.sleep(2)

            ret, frame = camera.read()

            if not ret:
                print("Failed to capture image.")
                return

            filename = "photo.jpg"
            cv2.imwrite(filename, frame)

            async with aiofiles.open(filename, "rb") as img_file:
                img_data = await img_file.read()
                encoded_img = base64.b64encode(img_data).decode("utf-8")

            # Check again if agent was banned during processing
            if not self.camera.requests.get(self.requester_jid, lambda _: True)(now):
                print(f"Agent {self.requester_jid} was banned during processing. Dropping response.")
                msg = Message(to=self.raw_requester_jid)
                msg.set_metadata("performative", "info")
                msg.body = "Request cancelled due to ban"
                await self.send(msg)
                return

            msg = Message(to=self.raw_requester_jid)
            msg.set_metadata("performative", "inform")
            msg.body = encoded_img

            self.camera.requests[self.requester_jid] = self.reset_timeout(now)
            self.camera.processing_complete.set()

            await self.send(msg)
            print("Photo sent.")

    class WaitForRequestBehaviour(behaviour.CyclicBehaviour):
        def __init__(self, camera):
            super().__init__()
            self.camera = camera

        async def run(self):
            print("Waiting for request...")
            msg = await self.receive(timeout=9999)
            if msg:
                print("Received camera image request.")
                requester_jid = str(msg.sender)
                self.agent.add_behaviour(
                    self.agent.SendPhotoBehaviour(requester_jid, self.camera)
                )

    async def setup(self):
        print(f"{self.jid} is ready.")
        # Start the HTTP server
        await self.start_http_server()
        # Keep the XMPP behaviors for photo requests
        self.add_behaviour(self.WaitForRequestBehaviour(self))

    async def stop(self):
        # Stop the HTTP server first
        await self.stop_http_server()
        # Then stop the agent
        await super().stop()
