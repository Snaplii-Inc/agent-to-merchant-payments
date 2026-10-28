// The platform compiles script.csx with every supported namespace already imported, from
// https://learn.microsoft.com/en-us/connectors/custom-connectors/write-code#supported-namespaces
// so a name that two of them share (Formatting is in System.Xml and Newtonsoft.Json) fails there.
global using System;
global using System.Collections;
global using System.Collections.Generic;
global using System.Diagnostics;
global using System.IO;
global using System.IO.Compression;
global using System.Linq;
global using System.Net;
global using System.Net.Http;
global using System.Net.Http.Headers;
global using System.Net.Security;
global using System.Security.Authentication;
global using System.Security.Cryptography;
global using System.Text;
global using System.Text.RegularExpressions;
global using System.Threading;
global using System.Threading.Tasks;
global using System.Web;
global using System.Xml;
global using System.Xml.Linq;
global using System.Drawing;
global using System.Drawing.Drawing2D;
global using System.Drawing.Imaging;
global using Microsoft.Extensions.Logging;
global using Newtonsoft.Json;
global using Newtonsoft.Json.Linq;
