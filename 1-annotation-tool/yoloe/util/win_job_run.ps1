# Start review service inside a Windows Job Object so closing the
# console window kills the python child and frees the port.
param(
  [Parameter(Mandatory = $true)][int]$Port,
  [string]$Dataset = "",
  [string]$Python = "python"
)

$ErrorActionPreference = "SilentlyContinue"

function Free-Port([int]$p) {
  Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
      $procId = $_.OwningProcess
      if ($procId) {
        Write-Host "  Free port $p (PID $procId)"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
      }
    }
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class KillJob {
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
  static extern IntPtr CreateJobObject(IntPtr a, string n);

  [DllImport("kernel32.dll", SetLastError = true)]
  static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint size);

  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

  [StructLayout(LayoutKind.Sequential)]
  struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
    public long PerProcessUserTimeLimit;
    public long PerJobUserTimeLimit;
    public uint LimitFlags;
    public UIntPtr MinimumWorkingSetSize;
    public UIntPtr MaximumWorkingSetSize;
    public uint ActiveProcessLimit;
    public long Affinity;
    public uint PriorityClass;
    public uint SchedulingClass;
  }

  [StructLayout(LayoutKind.Sequential)]
  struct IO_COUNTERS {
    public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
    public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
  }

  [StructLayout(LayoutKind.Sequential)]
  struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
    public IO_COUNTERS IoInfo;
    public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
  }

  const int JobObjectExtendedLimitInformation = 9;
  const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

  public static IntPtr Create() {
    IntPtr job = CreateJobObject(IntPtr.Zero, null);
    var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    int len = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
    IntPtr ptr = Marshal.AllocHGlobal(len);
    Marshal.StructureToPtr(info, ptr, false);
    SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)len);
    Marshal.FreeHGlobal(ptr);
    return job;
  }
}
"@

Free-Port $Port

$pyArgs = @("util\app.py", "--port", "$Port")
if ($Dataset -and $Dataset.Trim().Length -gt 0) {
  $pyArgs += @("--dataset", $Dataset.Trim())
}

$job = [KillJob]::Create()
$workDir = Split-Path -Parent $PSScriptRoot
$pyExe = if ($Python -and (Test-Path -LiteralPath $Python)) { $Python } else { "python" }
$proc = Start-Process -FilePath $pyExe -ArgumentList $pyArgs -WorkingDirectory $workDir -PassThru -NoNewWindow
if (-not $proc) {
  Write-Host "[ERROR] failed to start python: $pyExe"
  exit 1
}

if (-not [KillJob]::AssignProcessToJobObject($job, $proc.Handle)) {
  Write-Host "[WARN] Job Object assign failed; close window may leave port occupied"
}

try {
  Wait-Process -Id $proc.Id
} finally {
  if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
  Free-Port $Port
}
