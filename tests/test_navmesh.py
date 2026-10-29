"""The NeocronSharp --navplan client, with a fake process instead of the game."""
import json
import queue
import unittest

import navmesh

EXIT3 = {"name": "WorldChange3", "position": [-1024, -240, 3120], "index": 4, "nextLevel": 101, "nextLevelName": "PLAZA SEC-3",
         "nextLevelStartIndex": 1, "destinationKnown": True, "bearing": 92.03, "distance": 1417.28}
FROM = [-2440.39, -255.9, 3069.85]


def plan_answer(request, path, exit_=None, complete=True):
    answer = {"ok": True, "id": request["id"], "world": 1, "worldName": "PLAZA SEC-1", "mesh": "memory", "from": FROM,
              "path": path, "complete": complete, "length": 1417.28}
    if exit_ is not None:
        answer["exit"] = exit_
    return answer


def answer_like_neocronsharp(request):
    """What NeocronSharp answers (from a live Plaza SEC-1 run), or None to stay silent."""
    to = request.get("to")
    if to == "exits":
        unroutable = {**EXIT3, "name": "WorldChange13", "nextLevel": 1, "nextLevelName": "PLAZA SEC-1", "nextLevelStartIndex": 0,
                      "destinationKnown": False, "pathLength": None, "complete": False}
        return {"ok": True, "id": request["id"], "world": 1, "worldName": "PLAZA SEC-1", "mesh": "bake", "from": FROM,
                "exits": [{**EXIT3, "pathLength": 1417.28, "complete": True}, unroutable]}
    if to == "exit" and request.get("name", "").lower() == "worldchange3" or request.get("bearing") == 90.0:
        return plan_answer(request, [[-2433.6, -253.9, 3071.0], [-1024.0, -253.9, 3120.0]], EXIT3)
    if to == "exit" and "name" in request:
        return {"ok": False, "id": request["id"], "error": f"No exit named '{request['name']}' in PLAZA SEC-1."}
    if to == "point":
        if "y" in request:
            assert request["y"] == -250.0
        return plan_answer(request, [[-2433.6, -253.9, 3071.0], [-1650.0, -253.9, 3290.0], [-1656.0, -253.9, 3280.0]], complete=False)
    if to == "silent":
        return None
    return {"ok": False, "id": request["id"], "error": "The current sector is unavailable. Finish zoning."}


class FakeStdout:
    def __init__(self):
        self.lines = queue.Queue()

    def __iter__(self):
        while (line := self.lines.get()) is not None:
            yield line


class FakeStdin:
    def __init__(self, process):
        self.process, self.closed, self.buffer = process, False, ""

    def write(self, text):
        if self.closed:
            raise ValueError("closed")
        self.buffer += text

    def flush(self):
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            request = json.loads(line)
            self.process.requests.append(request)
            if request.get("to") == "late":       # answer an older id first, as after a timeout
                self.process.stdout.lines.put(json.dumps({"ok": True, "id": request["id"] - 1, "exits": []}) + "\n")
                request = {**request, "to": "exits"}
            if request.get("to") == "die":
                self.process.stdout.lines.put(None)
                self.process.dead = True
                continue
            answer = answer_like_neocronsharp(request)
            if answer is not None:
                self.process.stdout.lines.put(json.dumps(answer) + "\n")

    def close(self):
        self.closed = True
        self.process.stdout.lines.put(None)


class FakeProcess:
    def __init__(self):
        self.requests, self.dead, self.waited = [], False, False
        self.stdout = FakeStdout()
        self.stdin = FakeStdin(self)

    def poll(self):
        return 0 if self.dead or self.stdin.closed else None

    def wait(self, timeout=None):
        self.waited = True

    def kill(self):
        pass


class Launcher:
    def __init__(self):
        self.processes, self.commands = [], []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.processes.append(FakeProcess())
        return self.processes[-1]


class NavPlannerTests(unittest.TestCase):
    def setUp(self):
        self.launch = Launcher()
        self.planner = navmesh.NavPlanner(popen=self.launch, executable=__file__, timeout=2)

    def tearDown(self):
        self.planner.close()

    def test_exits_carry_destinations_and_routes(self):
        exits = self.planner.exits()
        self.assertEqual(self.launch.commands[0][1:], ["--navplan"])
        self.assertEqual([e.name for e in exits], ["WorldChange3", "WorldChange13"])
        three = exits[0]
        self.assertEqual((three.x, three.z, three.next_level, three.next_level_name, three.start_index), (-1024.0, 3120.0, 101, "PLAZA SEC-3", 1))
        self.assertTrue(three.destination_known and three.complete)
        self.assertEqual(three.path_length, 1417.28)
        self.assertIsNone(exits[1].path_length)
        self.assertFalse(exits[1].destination_known or exits[1].complete)

    def test_plan_to_exit_by_name_or_bearing_is_in_ground_coordinates(self):
        plan = self.planner.plan_to_exit("WorldChange3")
        self.assertEqual(plan.path, [(-2433.6, 3071.0), (-1024.0, 3120.0)])
        self.assertEqual(plan.heights, [-253.9, -253.9])
        self.assertEqual((plan.world, plan.world_name, plan.start, plan.complete), (1, "PLAZA SEC-1", (-2440.39, 3069.85), True))
        self.assertEqual(plan.exit.next_level_name, "PLAZA SEC-3")
        self.assertIsNone(plan.exit.path_length)
        self.assertEqual(self.planner.plan_to_exit(bearing=90).exit.name, "WorldChange3")
        self.assertEqual(self.launch.processes[0].requests[1], {"to": "exit", "bearing": 90.0, "id": 2})
        self.assertEqual(len(self.launch.processes), 1)          # one process serves every request
        with self.assertRaises(ValueError):
            self.planner.plan_to_exit()

    def test_plan_to_a_point_may_be_incomplete(self):
        plan = self.planner.plan_to(-1500, 3500)
        self.assertFalse(plan.complete)
        self.assertEqual(plan.path[-1], (-1656.0, 3280.0))
        self.assertIsNone(plan.exit)
        self.assertNotIn("y", self.launch.processes[0].requests[0])
        self.assertIsNotNone(self.planner.plan_to(-1500, 3500, y=-250))

    def test_failures_are_none_with_a_reason(self):
        self.assertIsNone(self.planner.plan_to_exit("Nope"))
        self.assertIn("No exit named", self.planner.error)
        self.assertIsNone(self.planner.request({"to": "zoning"}))
        self.assertIn("zoning", self.planner.error.lower())
        self.assertIsNone(self.planner.request({"to": "silent"}, timeout=0.05))
        self.assertIn("in time", self.planner.error)
        self.assertIsNotNone(self.planner.exits())               # recovers; a stale answer would be skipped by id
        self.assertIsNone(self.planner.error)

    def test_a_late_answer_to_an_old_request_is_skipped(self):
        data = self.planner.request({"to": "late"})
        self.assertEqual(data["id"], 1)
        self.assertIn("exits", data)

    def test_a_dead_process_is_restarted(self):
        self.assertIsNone(self.planner.request({"to": "die"}))
        self.assertIn("closed", self.planner.error)
        self.assertIsNotNone(self.planner.exits())
        self.assertEqual(len(self.launch.processes), 2)

    def test_close_ends_the_process(self):
        self.planner.exits()
        process = self.launch.processes[0]
        self.planner.close()
        self.assertTrue(process.stdin.closed and process.waited)

    def test_without_neocronsharp_everything_is_none(self):
        planner = navmesh.NavPlanner(executable="C:/nowhere/NeocronSharp.exe")
        self.assertIsNone(planner.exits())
        self.assertIsNone(planner.plan_to(0, 0))
        self.assertIn("not built", planner.error)
        planner.close()


if __name__ == "__main__":
    unittest.main()
