using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Security.Cryptography;

namespace ClashAssistant.Desktop.Services;

/// <summary>Owns one cached, multi-resolution tray icon and its stable fingerprint.</summary>
internal sealed class TrayStateIcon : IDisposable
{
    public Icon Icon { get; }
    public string Fingerprint { get; }

    public TrayStateIcon(Icon baseIcon, bool running)
    {
        byte[] bytes = Encode(baseIcon, running);
        Fingerprint = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        using MemoryStream stream = new(bytes, writable: false);
        Icon = new Icon(stream, 32, 32);
    }

    // The existing blue crown remains the application's identity. A large badge
    // also changes shape, so state is readable without relying on colour alone.
    internal static Bitmap Render(Icon baseIcon, bool running, int size)
    {
        if (size < 16 || size > 256) throw new ArgumentOutOfRangeException(nameof(size));
        Bitmap bitmap = new(size, size, PixelFormat.Format32bppArgb);
        using Graphics graphics = Graphics.FromImage(bitmap);
        graphics.Clear(Color.Transparent);
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
        using Icon sizedIcon = new(baseIcon, size, size);
        graphics.DrawIcon(sizedIcon, new Rectangle(0, 0, size, size));

        float unit = size / 16f;
        RectangleF badge = new(7.125f * unit, 7.125f * unit, 8.625f * unit, 8.625f * unit);
        using SolidBrush background = new(running ? Color.FromArgb(17, 155, 81) : Color.FromArgb(94, 105, 124));
        using Pen outline = new(Color.White, 0.75f * unit);
        graphics.FillEllipse(background, badge);
        graphics.DrawEllipse(outline, badge);
        using SolidBrush symbol = new(Color.White);
        if (running)
        {
            graphics.FillPolygon(symbol, new PointF[]
            {
                new(10.3f * unit, 9.25f * unit),
                new(14.1f * unit, 11.45f * unit),
                new(10.3f * unit, 13.65f * unit)
            });
        }
        else
        {
            // Pixel-aligned bars remain distinct at the smallest taskbar size.
            graphics.FillRectangle(symbol, 10f * unit, 9.5f * unit, 1.35f * unit, 4f * unit);
            graphics.FillRectangle(symbol, 12.4f * unit, 9.5f * unit, 1.35f * unit, 4f * unit);
        }
        return bitmap;
    }

    private static byte[] Encode(Icon baseIcon, bool running)
    {
        int[] sizes = { 16, 20, 24, 32, 40, 48, 64 };
        List<byte[]> frames = new(sizes.Length);
        foreach (int size in sizes)
        {
            using Bitmap bitmap = Render(baseIcon, running, size);
            frames.Add(EncodeFrame(bitmap));
        }

        using MemoryStream output = new();
        using BinaryWriter writer = new(output);
        writer.Write((ushort)0); writer.Write((ushort)1); writer.Write((ushort)sizes.Length);
        int imageOffset = 6 + 16 * sizes.Length;
        for (int index = 0; index < sizes.Length; index++)
        {
            writer.Write((byte)sizes[index]); writer.Write((byte)sizes[index]);
            writer.Write((byte)0); writer.Write((byte)0);
            writer.Write((ushort)1); writer.Write((ushort)32);
            writer.Write(frames[index].Length); writer.Write(imageOffset);
            imageOffset += frames[index].Length;
        }
        foreach (byte[] frame in frames) writer.Write(frame);
        return output.ToArray();
    }

    private static byte[] EncodeFrame(Bitmap bitmap)
    {
        int size = bitmap.Width;
        int maskStride = ((size + 31) / 32) * 4;
        int imageLength = size * size * 4 + maskStride * size;
        using MemoryStream output = new(40 + imageLength);
        using BinaryWriter writer = new(output);
        // Encode the 32-bit DIB directly: Icon.FromHandle().Save() may reduce
        // a frame to a 16-colour palette and discard the badge's alpha edges.
        // This also avoids creating any temporary, caller-owned HICON handle.
        writer.Write(40); writer.Write(size); writer.Write(size * 2);
        writer.Write((ushort)1); writer.Write((ushort)32);
        writer.Write(0); writer.Write(imageLength);
        writer.Write(0); writer.Write(0); writer.Write(0); writer.Write(0);
        for (int y = size - 1; y >= 0; y--)
        {
            for (int x = 0; x < size; x++)
            {
                Color pixel = bitmap.GetPixel(x, y);
                writer.Write(pixel.B); writer.Write(pixel.G); writer.Write(pixel.R); writer.Write(pixel.A);
            }
        }
        byte[] mask = new byte[maskStride];
        for (int y = size - 1; y >= 0; y--)
        {
            Array.Clear(mask);
            for (int x = 0; x < size; x++)
            {
                if (bitmap.GetPixel(x, y).A == 0) mask[x / 8] |= (byte)(0x80 >> (x % 8));
            }
            writer.Write(mask);
        }
        return output.ToArray();
    }

    public void Dispose() => Icon.Dispose();
}
