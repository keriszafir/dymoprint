# === LICENSE STATEMENT ===
# Copyright (c) 2011 Sebastian J. Bronner <waschtl@sbronner.com>
#
# Copying and distribution of this file, with or without modification, are
# permitted in any medium without royalty provided the copyright notice and
# this notice are preserved.
# === END LICENSE STATEMENT ===

import argparse
import array
import math
import os

import barcode as barcode_module
import usb
from PIL import Image, ImageFont, ImageOps

from . import DymoLabeler, __version__
from .barcode_writer import BarcodeImageWriter
from .constants import (
    DEV_CLASS,
    DEV_LM280_CLASS,
    DEV_LM280_NAME,
    DEV_LM280_PRODUCT,
    DEV_NAME,
    DEV_NODE,
    DEV_PRODUCT,
    DEV_VENDOR,
    FONT_SIZERATIO,
    USE_QR,
    QRCode,
    e_qrcode,
)
from .font_config import font_filename
from .metadata import our_metadata
from .unicode_blocks import image_to_unicode
from .utils import access_error, die, draw_image, getDeviceFile, scaling


def parse_args():

    # check for any text specified on the command line
    parser = argparse.ArgumentParser(description=our_metadata["Summary"])
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "text",
        nargs="+",
        help="Text Parameter, each parameter gives a new line",
        type=str,
    )
    parser.add_argument(
        "-f",
        action="count",
        help="Draw frame around the text, more arguments for thicker frame",
    )
    parser.add_argument(
        "-s",
        choices=["r", "b", "i", "n"],
        default="r",
        help="Set fonts style (regular,bold,italic,narrow)",
    )
    parser.add_argument("-u", nargs="?", help='Set user font, overrides "-s" parameter')
    parser.add_argument(
        "-n",
        "--preview",
        action="store_true",
        help="Unicode preview of label, do not send to printer",
    )
    parser.add_argument(
        "--preview-inverted",
        action="store_true",
        help="Unicode preview of label, colors inverted, do not send to printer",
    )
    parser.add_argument(
        "--imagemagick",
        action="store_true",
        help="Preview label with Imagemagick, do not send to printer",
    )
    parser.add_argument(
        "-qr", action="store_true", help="Printing the first text parameter as QR-code"
    )
    parser.add_argument(
        "-c",
        choices=[
            "code39",
            "code128",
            "ean",
            "ean13",
            "ean8",
            "gs1",
            "gtin",
            "isbn",
            "isbn10",
            "isbn13",
            "issn",
            "jan",
            "pzn",
            "upc",
            "upca",
        ],
        default=False,
        help="Printing the first text parameter as barcode",
    )
    parser.add_argument("-p", "--picture", help="Print the specified picture")
    parser.add_argument("-m", type=int, help="Override margin (default is 56*2)")
    # parser.add_argument('-t',type=int,choices=[6, 9, 12],default=12,help='Tape size: 6,9,12 mm, default=12mm')
    return parser.parse_args()


def main():
    args = parse_args()

    # read config file
    FONT_FILENAME = font_filename(args.s)

    labeltext = args.text

    if args.u is not None:
        if os.path.isfile(args.u):
            FONT_FILENAME = args.u
        else:
            die("Error: file '%s' not found." % args.u)

    # check if barcode, qrcode or text should be printed, use frames only on text
    if args.qr and not USE_QR:
        die("Error: %s" % e_qrcode)

    if args.c and args.qr:
        die("Error: can not print both QR and Barcode on the same label (yet)")

    bitmaps = []

    if args.qr:
        # create QR object from first string
        code = QRCode(labeltext.pop(0), error="M")
        qr_text = code.text(quiet_zone=1).split()

        # create an empty label image
        labelheight = DymoLabeler._MAX_BYTES_PER_LINE * 8
        labelwidth = labelheight
        qr_scale = labelheight // len(qr_text)
        qr_offset = (labelheight - len(qr_text) * qr_scale) // 2

        if not qr_scale:
            die(
                "Error: too much information to store in the QR code, points are smaller than the device resolution"
            )

        codebitmap = Image.new("1", (labelwidth, labelheight))

        with draw_image(codebitmap) as labeldraw:
            # write the qr-code into the empty image
            for i, line in enumerate(qr_text):
                for j in range(len(line)):
                    if line[j] == "1":
                        pix = scaling(
                            (j * qr_scale, i * qr_scale + qr_offset), qr_scale
                        )
                        labeldraw.point(pix, 255)

        bitmaps.append(codebitmap)

    elif args.c:
        code = barcode_module.get(args.c, labeltext.pop(0), writer=BarcodeImageWriter())
        codebitmap = code.render(
            {
                "font_size": 0,
                "vertical_margin": 8,
                "module_height": (DymoLabeler._MAX_BYTES_PER_LINE * 8) - 16,
                "module_width": 2,
                "background": "black",
                "foreground": "white",
            }
        )

        bitmaps.append(codebitmap)

    if labeltext:
        if args.f == None:
            fontoffset = 0
        else:
            fontoffset = min(args.f, 3)

        # create an empty label image
        labelheight = DymoLabeler._MAX_BYTES_PER_LINE * 8
        lineheight = float(labelheight) / len(labeltext)
        fontsize = int(round(lineheight * FONT_SIZERATIO))
        font = ImageFont.truetype(FONT_FILENAME, fontsize)
        labelwidth = max(font.getsize(line)[0] for line in labeltext) + (fontoffset * 2)
        textbitmap = Image.new("1", (labelwidth, labelheight))
        with draw_image(textbitmap) as labeldraw:

            # draw frame into empty image
            if args.f is not None:
                labeldraw.rectangle(
                    ((0, 0), (labelwidth - 1, labelheight - 1)), fill=255
                )
                labeldraw.rectangle(
                    (
                        (fontoffset, fontoffset),
                        (labelwidth - (fontoffset + 1), labelheight - (fontoffset + 1)),
                    ),
                    fill=0,
                )

            # write the text into the empty image
            for i, line in enumerate(labeltext):
                lineposition = int(round(i * lineheight))
                labeldraw.text((fontoffset, lineposition), line, font=font, fill=255)

        bitmaps.append(textbitmap)

    if args.picture:
        labelheight = DymoLabeler._MAX_BYTES_PER_LINE * 8
        with Image.open(args.picture) as img:
            if img.height > labelheight:
                ratio = labelheight / img.height
                img.thumbnail(
                    (int(math.ceil(img.width * ratio)), labelheight), Image.ANTIALIAS
                )
            bitmaps.append(ImageOps.invert(img).convert("1"))

    if len(bitmaps) > 1:
        padding = 4
        labelbitmap = Image.new(
            "1",
            (
                sum(b.width for b in bitmaps) + padding * (len(bitmaps) - 1),
                bitmaps[0].height,
            ),
        )
        offset = 0
        for bitmap in bitmaps:
            labelbitmap.paste(bitmap, box=(offset, 0))
            offset += bitmap.width + padding
    else:
        labelbitmap = bitmaps[0]

    # convert the image to the proper matrix for the dymo labeler object
    labelrotated = labelbitmap.transpose(Image.ROTATE_270)
    labelstream = labelrotated.tobytes()
    labelstreamrowlength = int(math.ceil(labelbitmap.height / 8))
    if len(labelstream) // labelstreamrowlength != labelbitmap.width:
        die("An internal problem was encountered while processing the label " "bitmap!")
    labelrows = [
        labelstream[i : i + labelstreamrowlength]
        for i in range(0, len(labelstream), labelstreamrowlength)
    ]
    labelmatrix = [array.array("B", labelrow).tolist() for labelrow in labelrows]

    # print or show the label
    if args.preview or args.preview_inverted or args.imagemagick:
        print("Demo mode: showing label..")
        # fix size, adding print borders
        labelimage = Image.new("L", (56 + labelbitmap.width + 56, labelbitmap.height))
        labelimage.paste(labelbitmap, (56, 0))
        if args.preview or args.preview_inverted:
            print(image_to_unicode(labelrotated, invert=args.preview_inverted))
        if args.imagemagick:
            ImageOps.invert(labelimage).show()
    else:
        # get device file name
        if not DEV_NODE:
            dev = getDeviceFile(DEV_CLASS, DEV_VENDOR, DEV_PRODUCT)
        else:
            dev = DEV_NODE

        if dev:
            devout = open(dev, "rb+")
            devin = devout
            # We are in the normal HID file mode, so no synwait is needed.
            synwait = None
        else:
            # We are in the experimental PyUSB mode, if a device can be found.
            synwait = 64
            # Find and prepare device communication endpoints.
            dev = usb.core.find(
                custom_match=lambda d: (
                    d.idVendor == DEV_VENDOR and d.idProduct == DEV_LM280_PRODUCT
                )
            )

            if dev is None:
                device_not_found()
            else:
                print("Entering experimental PyUSB mode.")

            try:
                dev.set_configuration()
            except usb.core.USBError as e:
                if e.errno == 13:
                    raise RuntimeError("Access denied")
                if e.errno == 16:
                    # Resource busy
                    pass
                else:
                    raise

            intf = usb.util.find_descriptor(
                dev.get_active_configuration(), bInterfaceClass=DEV_LM280_CLASS
            )
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                dev.detach_kernel_driver(intf.bInterfaceNumber)
            devout = usb.util.find_descriptor(
                intf,
                custom_match=(
                    lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT
                ),
            )
            devin = usb.util.find_descriptor(
                intf,
                custom_match=(
                    lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_IN
                ),
            )

        if not devout or not devin:
            device_not_found()

        # create dymo labeler object
        try:
            lm = DymoLabeler(devout, devin, synwait=synwait)
        except IOError:
            die(access_error(dev))

        print("Printing label..")
        if args.m is not None:
            lm.printLabel(labelmatrix, margin=args.m)
        else:
            lm.printLabel(labelmatrix)


def device_not_found():
    die("The device '%s' could not be found on this system." % DEV_NAME)
