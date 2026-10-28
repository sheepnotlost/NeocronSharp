using System.Numerics;
using NeocronSharp.Core;

int passed = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
void Test(string name, Action action) { action(); Console.WriteLine($"PASS {name}"); passed++; }
void Reject(Action action) { try { action(); } catch (InvalidOperationException) { return; } throw new Exception("Expected rejection"); }
Vector3 P(float x, float z = 0) => new(x, 0, z);

Test("Four measured legs in requested endpoint order", () => {
    var route = new StraightLineRoute(P(0), P(100));
    Check(route.CompletedLegs == 1, "Recorded first leg counts once");
    Check(route.Observe(P(100)).Input == TravelInput.Backward, "First return uses backward");
    Check(!route.Observe(P(50)).Arrived, "Midpoint is not arrival");
    Check(route.Observe(P(0)).CompletedLegs == 2, "Second leg ends at A");
    Check(route.Observe(P(0)).Input == TravelInput.Forward, "Second outbound uses forward");
    Check(route.Observe(P(100)).CompletedLegs == 3, "Third leg ends at B");
    Check(route.Observe(P(0)).Complete, "Fourth leg ends at A");
    Check(route.Observe(P(0)).Input == TravelInput.None, "Completed route sends no input");
});
Test("Unequal forward/backward speeds still return to A", () => {
    var route = new StraightLineRoute(P(0), P(120));
    Vector3 position = P(120);
    int steps;
    for (steps = 0; steps < 2000 && !route.Complete; steps++) {
        var decision = route.Observe(position);
        position.X += decision.Input == TravelInput.Forward ? 1.8f : decision.Input == TravelInput.Backward ? -0.7f : 0;
    }
    Check(route.Complete && Math.Abs(position.X) <= route.Tolerance, "Must measure return, not match duration");
});
Test("Small overshoot requests correction", () => {
    var route = new StraightLineRoute(P(0), P(100));
    Check(route.Observe(P(-2)).Input == TravelInput.Forward, "Correct overshoot on return");
});
Test("Sideways movement stops", () => Reject(() => new StraightLineRoute(P(0), P(100)).Observe(P(50, 10))));
Test("Large overshoot stops", () => Reject(() => new StraightLineRoute(P(0), P(100)).Observe(P(-30))));
Test("NaN telemetry stops", () => Reject(() => new StraightLineRoute(P(0), P(100)).Observe(P(float.NaN))));
Test("Uninitialized segment is rejected", () => Reject(() => new StraightLineRoute(P(0), P(0))));
Test("Long segment is rejected", () => Reject(() => new StraightLineRoute(P(0), P(401))));
Test("Near endpoint with lateral error is not success", () => Reject(() => new StraightLineRoute(P(0), P(100)).Observe(P(0, 3))));
Test("Diagonal direction preserves straight-line projection", () => {
    var route = new StraightLineRoute(P(0), P(60, 80));
    Check(route.Observe(P(30, 40)).Input == TravelInput.Backward, "Diagonal return");
    Check(route.Observe(P(0)).Arrived, "Diagonal measured endpoint");
});
Test("Live endpoint drift is corrected before counting arrival", () => {
    var route = new StraightLineRoute(new(-1631.6165f,-255.9f,781.7576f), new(-1531.959f,-255.9f,775.9799f));
    var preview = route.Observe(new(-1631.2177f,-255.9f,781.73444f), commitArrival:false);
    Check(preview.Arrived && route.CompletedLegs == 1, "Proximity alone must not count a leg");
    var drift = route.Observe(new(-1629.1101f,-255.9f,781.61224f));
    Check(!drift.Arrived && drift.Input == TravelInput.Backward && route.CompletedLegs == 1, "Settled drift must request correction");
    Check(route.Observe(route.A).CompletedLegs == 2, "Only settled arrival counts");
});
Test("Navigation turns before moving sideways toward a destination", () => {
    var decision = PointNavigation.Decide(Vector3.Zero, P(0, -1), P(100), 0.004f);
    Check(decision.Travel == TravelInput.None && decision.MouseX > 0, "Turn in place first");
});
Test("Navigation handles inverted mouse response", () => {
    var decision = PointNavigation.Decide(Vector3.Zero, P(0, -1), P(100), -0.004f);
    Check(decision.Travel == TravelInput.None && decision.MouseX < 0, "Measured response controls steering sign");
});
Test("Heading wrap takes the short turn across 180 degrees", () => {
    float a = 179 * MathF.PI / 180, b = -179 * MathF.PI / 180;
    float angle = PointNavigation.SignedAngle(P(MathF.Cos(a),MathF.Sin(a)), P(MathF.Cos(b),MathF.Sin(b)));
    Check(Math.Abs(angle - 2*MathF.PI/180) < 0.0001f, "Take two-degree turn, not a full circle");
});
Test("Small navigation overshoot uses backward correction", () => {
    var decision = PointNavigation.Decide(P(4), P(1), P(0), 0.004f);
    Check(decision.Travel == TravelInput.Backward && decision.MouseX == 0, "Correct without a 180-degree turn");
});
Test("Distant destination behind the character requires turning", () => {
    var decision = PointNavigation.Decide(P(100), P(1), P(0), 0.004f);
    Check(decision.Travel == TravelInput.None && decision.MouseX != 0, "Turn before long-distance travel");
});
Test("Different floor is rejected", () => Reject(() => PointNavigation.Decide(Vector3.Zero,P(1),new(10,20,0),0.004f)));
Test("Destination directly above is not a successful arrival", () => Reject(() => PointNavigation.Decide(Vector3.Zero,P(1),new(0,5,0),0.004f)));
Test("Uncalibrated steering is rejected", () => Reject(() => PointNavigation.Decide(Vector3.Zero,P(1),P(100),0)));
Test("Native transform heading ignores pitch", () => {
    float pitch = 0.4f;
    float[] transform = {1,0,0, 0,MathF.Cos(pitch),MathF.Sin(pitch), 0,-MathF.Sin(pitch),MathF.Cos(pitch), 10,20,30};
    var forward = PointNavigation.ForwardFromTransform(transform);
    Check(Vector3.Distance(forward,P(0,-1)) < 0.00001f, "Heading lies on the ground plane");
});
Test("Corrupt transform is rejected", () => Reject(() => PointNavigation.ForwardFromTransform(new float[12])));
Test("Incorrect native forward convention cannot enable navigation", () => Reject(() => PointNavigation.VerifyForward(P(1),P(-10))));
Test("Forward calibration rejects blocked movement", () => Reject(() => PointNavigation.VerifyForward(P(1),Vector3.Zero)));
Test("Point navigation converges with movement inertia from different headings", () => {
    foreach (float initialHeading in new[]{0f,0.8f,2.1f,-2.9f})
    foreach (float gain in new[]{0.004f,-0.004f}) {
        Vector3 pos = P(100,40), velocity = Vector3.Zero;
        float heading = initialHeading;
        bool complete = false;
        for (int step=0;step<5000;step++) {
            Vector3 forward = P(MathF.Cos(heading),MathF.Sin(heading));
            var decision = PointNavigation.Decide(pos,forward,Vector3.Zero,gain);
            heading += decision.MouseX*gain;
            var desired = forward*(decision.Travel == TravelInput.Forward ? 100 : decision.Travel == TravelInput.Backward ? -60 : 0);
            velocity = velocity*0.35f+desired*0.65f;
            pos += velocity*0.01f;
            if(decision.NearDestination && velocity.Length()<0.05f) { complete=true;break; }
        }
        Check(complete && pos.Length()<=PointNavigation.ArrivalTolerance, $"Failed heading={initialHeading}, gain={gain}");
    }
});
Test("User's 418 and 709 unit destinations are accepted", () => {
    foreach(float distance in new[]{417.98044f,445.3849f,708.8597f}) {
        PointNavigation.ValidateDestination(P(0),P(distance));
        Check(PointNavigation.Decide(P(0),P(1),P(distance),0.004f).Travel==TravelInput.Forward,"Nearby street destination must start");
    }
});
Test("Range checks still reject another distant area", () => Reject(() => PointNavigation.ValidateDestination(P(0),P(10001))));
Test("Observed second outbound overshoot requests correction", () => {
    var route=new StraightLineRoute(new(-1256.883f,-255.9f,831.1021f),new(-1158.68f,-255.9f,808.45874f));
    route.Observe(route.A);
    var correction=route.Observe(new(-1154.0371f,-255.9f,807.3884f));
    Check(correction.Input==TravelInput.Backward && route.CompletedLegs==2,"On-line overshoot is recoverable, not sideways deviation");
});
Test("Steering pulses preserve sign and total correction", () => {
    foreach(int requested in Enumerable.Range(-24,49)) {
        var pulses=SteeringPulses.Split(requested).ToArray();
        Check(pulses.Sum()==requested && pulses.All(p=>Math.Abs(p)<=2 && Math.Sign(p)==Math.Sign(requested)),"Every correction must be spread into bounded frame samples");
    }
});
ActorTests.Run(Test, Check);
NpcDataTests.Run(Test, Check);
MapTests.Run(Test, Check);
ExpansionTests.Run(Test, Check);
PlayerTests.Run(Test, Check);
OrderingTests.Run(Test, Check);
CoordinateRecordingTests.Run(Test, Check);
QuestTests.Run(Test, Check);
PluginTests.Run(Test, Check);
Console.WriteLine($"{passed} tests passed.");
