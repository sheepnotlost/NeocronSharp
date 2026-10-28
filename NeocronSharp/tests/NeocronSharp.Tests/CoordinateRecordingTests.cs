using System.Globalization;
using System.Numerics;
using System.Text.Json;
using NeocronSharp.Core;

internal static class CoordinateRecordingTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        DateTimeOffset start = new(2026,10,28,3,0,0,TimeSpan.Zero);
        CoordinateFix Fix(long milliseconds, Vector3 position, int sector = 1) => new(start.AddMilliseconds(milliseconds),milliseconds,1,0x10000,0x20000,sector,270,position,-Vector3.UnitZ);
        void Reject(Action action) { try { action(); } catch (InvalidOperationException) { return; } throw new Exception("Invalid recording operation accepted"); }
        test("Coordinate recording retains stationary samples, precise height, monotonic time and heading", () =>
        {
            var log=new CoordinateRecording("Survey",100,start,0);
            var first=log.Append(Fix(0,new(1.25f,12.75f,-3.5f)),"Plaza");
            var second=log.Append(Fix(100,new(1.25f,12.75f,-3.5f)) with{Forward=Vector3.UnitX},"Plaza");
            check(log.Points.Count==2 && second.ElapsedMilliseconds==100 && second.Y==12.75f && second.HeadingDegrees==90,"Stationary/time/height data was lost");
            check(first.BreakReason=="Start" && first.Segment==1 && second.BreakReason=="" && log.DistanceWorldUnits==0,"An ordinary stationary sample must not create a route break");
        });
        test("Sector and client-session changes split trails without counting cross-zone travel", () =>
        {
            var log=new CoordinateRecording("Survey",100,start,0);
            log.Append(Fix(0,new(0,10,0)),"A");log.Append(Fix(100,new(3,14,0)),"A");
            var zone=log.Append(Fix(200,new(200,90,200),2),"B");
            log.Append(Fix(300,new(203,94,200),2),"B");
            var session=log.Append(Fix(400,new(800,40,800),2) with{ProcessId=2},"B");
            check(zone.Segment==2 && zone.BreakReason=="Sector changed" && session.Segment==3 && session.BreakReason=="Client session changed","Zone/session segments are incorrect");
            check(log.DistanceWorldUnits==10,"Cross-zone/session displacement must not count as walked distance");
        });
        test("Missing telemetry is recorded once per gap and never manufactures position samples", () =>
        {
            var log=new CoordinateRecording("Survey",100,start,0);log.Append(Fix(0,Vector3.One),"A");
            log.MarkGap(start.AddMilliseconds(100),"Zoning");log.MarkGap(start.AddMilliseconds(200),"Still zoning");
            check(log.Points.Count==1 && log.Gaps.Count==1,"Unavailable data should not append stale samples or duplicate gap events");
            var resumed=log.Append(Fix(300,new(8,8,8)),"A");
            check(resumed.Segment==2 && resumed.BreakReason=="Telemetry gap" && log.DistanceWorldUnits==0,"Resume must begin a new disconnected segment");
        });
        test("Long sampling pauses and large position discontinuities break the trail", () =>
        {
            var log=new CoordinateRecording("Survey",100,start,0);log.Append(Fix(0,Vector3.One),"A");
            var pause=log.Append(Fix(2500,new(2,2,2)),"A");var jump=log.Append(Fix(2600,new(5000,2,2)),"A");
            check(pause.BreakReason=="Sampling gap" && jump.BreakReason=="Position discontinuity" && jump.Segment==3 && log.DistanceWorldUnits==0,"Unobserved travel must not become a connecting route");
        });
        test("Invalid coordinates, sector, clock and stopped recordings cannot append data", () =>
        {
            var log=new CoordinateRecording("Survey",100,start,0);log.Append(Fix(100,Vector3.One),"A");
            Reject(()=>log.Append(Fix(200,new(float.NaN,1,1)),"A"));Reject(()=>log.Append(Fix(200,Vector3.One,0),"A"));
            Reject(()=>log.Append(Fix(50,Vector3.One),"A"));Reject(()=>log.Append(Fix(200,Vector3.One) with{Forward=Vector3.Zero},"A"));
            log.Stop(start.AddSeconds(1));Reject(()=>log.Append(Fix(300,Vector3.One),"A"));
            check(log.Points.Count==1 && !log.IsRecording,"Rejected samples must not change the recording");
        });
        test("CSV is readable during recording and CSV/JSON preserve coordinates under a comma-decimal locale", () =>
        {
            string folder=Path.Combine(Path.GetTempPath(),"NeocronSharp-coordinate-test-"+Guid.NewGuid().ToString("N"));
            var old=CultureInfo.CurrentCulture;
            try
            {
                CultureInfo.CurrentCulture=CultureInfo.GetCultureInfo("de-DE");
                var log=new CoordinateRecording("../:Survey",100,start,0);using var writer=new CoordinateLogWriter(folder,log);
                writer.Append(log.Append(Fix(0,new(1.25f,2.5f,-3.75f)),"Plaza, \"one\""));
                string csv;
                using (var input=new StreamReader(new FileStream(writer.CsvPath,FileMode.Open,FileAccess.Read,FileShare.ReadWrite))) csv=input.ReadToEnd();
                check(csv.Contains("1.25,2.5,-3.75") && csv.Contains("\"Plaza, \"\"one\"\"\""),"CSV numbers and quoted labels must be portable");
                check(csv.Split('\n',StringSplitOptions.RemoveEmptyEntries).Length==2 && !File.Exists(writer.JsonPath),"CSV must be flushed live; full JSON is finalized on Stop");
                check(Path.GetDirectoryName(writer.CsvPath)==folder,"Recording names must not change the save directory");
                Reject(()=>writer.Complete(log));log.Stop(start.AddSeconds(1));writer.Complete(log);
                using var json=JsonDocument.Parse(File.ReadAllText(writer.JsonPath));
                check(json.RootElement.GetProperty("Points")[0].GetProperty("X").GetSingle()==1.25f && json.RootElement.GetProperty("StoppedAtUtc").GetDateTimeOffset()==start.AddSeconds(1),"JSON coordinate/stop-time export failed");
            }
            finally { CultureInfo.CurrentCulture=old;if(Directory.Exists(folder)){foreach(string file in Directory.GetFiles(folder))File.Delete(file);Directory.Delete(folder);} }
        });
        test("Coordinate session memory has a visible bounded sample limit", () =>
        {
            var log=new CoordinateRecording("Survey",100,start,0);
            for(int i=0;i<CoordinateRecording.MaxSamples;i++) log.Append(Fix(i*100L,Vector3.One),"A");
            Reject(()=>log.Append(Fix(CoordinateRecording.MaxSamples*100L,Vector3.One),"A"));
            check(log.Points.Count==CoordinateRecording.MaxSamples,"Sample limit must not discard existing recorded data");
        });
    }
}
