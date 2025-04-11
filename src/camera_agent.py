import asyncio
import base64
from time import time

import aiofiles
import cv2
from spade import agent, behaviour
from spade.message import Message


class CameraAgent(agent.Agent):
    def __init__(self, jid, password):
        super().__init__(jid, password)
        # picture requests logging
        # as per default 500ms timeout
        self.timeout = 500  # ms
        self.ban_timeout = 10000  # ms
        self.requests: dict = {}

    class SendPhotoBehaviour(behaviour.OneShotBehaviour):
        def __init__(self, requester_jid, camera):
            super().__init__()
            self.requester_jid = requester_jid
            self.camera = camera
            self.reset_timeout = lambda last: (
                lambda now: int(round((now - last) * 1000))
                >= self.camera.timeout
            )

        async def run(self):
            now = time()

            # check if last request exceeded
            # predefined timeout
            if self.camera.requests.get(self.requester_jid, lambda _: True)(
                now
            ):
                self.camera.requests[self.requester_jid] = self.reset_timeout(
                    now
                )
            else:
                print("Request under timeout. No response..")
                return

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

            msg = Message(to=self.requester_jid)
            msg.set_metadata("performative", "inform")
            msg.body = encoded_img

            self.camera.requests[self.requester_jid] = self.reset_timeout(now)
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

    class BanRequestBehaviour(behaviour.CyclicBehaviour):
        def __init__(self, camera):
            super().__init__()
            self.camera = camera
            self.reset_timeout = lambda last: (
                lambda now: int(round((now - last) * 1000))
                >= self.camera.ban_timeout
            )

        async def run(self):
            msg = await self.receive(timeout=9999)
            if msg and msg.get_metadata("performative") == "ban":
                now = time()
                target_jid = msg.body
                self.camera.requests[target_jid] = self.reset_timeout(now)
                print(
                    f"Agent {target_jid} has been banned for {self.camera.ban_timeout}ms)"
                )

                # Optionally, send confirmation
                reply = Message(to=str(msg.sender))
                reply.set_metadata("performative", "confirm")
                reply.body = f"Agent {target_jid} has been banned"
                await self.send(reply)

    async def setup(self):
        print(f"{self.jid} is ready.")
        # Instead of immediately sending a photo, wait for requests
        self.add_behaviour(self.WaitForRequestBehaviour(self))
        self.add_behaviour(self.BanRequestBehaviour(self))
