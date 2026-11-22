if(-not ('Cloudragon.Moba.Shortcuts' -as [type])){
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
namespace Cloudragon.Moba {
 [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
 internal class ShellLink { }
 [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
 internal interface IShellLinkW {
  void GetPath([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder path,int count,IntPtr data,uint flags);
  void GetIDList(out IntPtr id); void SetIDList(IntPtr id);
  void GetDescription([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder text,int count);
  void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
  void GetWorkingDirectory([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder text,int count);
  void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string text);
  void GetArguments([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder text,int count);
  void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string text);
  void GetHotkey(out short key); void SetHotkey(short key);
  void GetShowCmd(out int command); void SetShowCmd(int command);
  void GetIconLocation([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder text,int count,out int index);
  void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string text,int index);
  void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string text,uint reserved);
  void Resolve(IntPtr window,uint flags);
  void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
 }
 public static class Shortcuts {
  public static void Save(string file,string target,string args,string directory,string description,int show) {
   object obj=new ShellLink();
   try { var link=(IShellLinkW)obj;link.SetPath(target);link.SetArguments(args);link.SetWorkingDirectory(directory);link.SetDescription(description);link.SetShowCmd(show);((IPersistFile)obj).Save(file,true); }
   finally { Marshal.FinalReleaseComObject(obj); }
  }
  public static string[] Read(string file) {
   object obj=new ShellLink();
   try { ((IPersistFile)obj).Load(file,0);var link=(IShellLinkW)obj;var target=new StringBuilder(32768);var args=new StringBuilder(32768);link.GetPath(target,target.Capacity,IntPtr.Zero,0);link.GetArguments(args,args.Capacity);return new[]{target.ToString(),args.ToString()}; }
   finally { Marshal.FinalReleaseComObject(obj); }
  }
 }
}
'@
}
