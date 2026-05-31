# Barcode Scanner Setup Guide

## Recommended Hardware

### Top Pick: Honeywell Voyager 1200g (~$75–100)
The Voyager 1200g is the best choice for a home library. It's the same scanner used in libraries and retail stores worldwide.

**Why it's the best pick:**
- Reads ISBN-10, ISBN-13, and EAN-13 barcodes without configuration
- USB HID mode — recognized as a keyboard by every OS with zero driver installation
- Fast decode (under 100ms) and works with worn or slightly damaged barcodes
- Very durable, designed for daily use

**Where to buy:** Amazon, eBay (refurbished units are fine), or direct from Honeywell resellers.

---

### Wireless Option: Inateck BCST-70 (~$40–50)
If you want to scan books from across the room without a USB cable tethered to your computer:

- 2.4GHz wireless via USB dongle (works like a wireless keyboard)
- Can also be used wired (USB-C charging cable)
- ~100m range indoors
- USB HID — no drivers needed
- Charges via USB-C

---

### Budget Wired Option: TaoTronics TT-BS002 (~$25–35)
- Works well for occasional use
- USB HID, no drivers
- Less reliable on worn barcodes than the Honeywell, but fine for books in good condition

---

## How USB HID Scanners Work

USB HID (Human Interface Device) scanners register with your computer as a keyboard. When you press the trigger and scan a barcode, the scanner:

1. Types the barcode digits as if you pressed the number keys
2. Sends an **Enter** keypress at the end

The Family Library app uses this behavior: the Scan page keeps the ISBN input focused, so every scan automatically fills the field and triggers a lookup. **No special software or drivers needed.**

---

## Setup Instructions

### Step 1 — Plug In

Connect the scanner's USB cable (or wireless dongle) to **the computer running the browser**, not the server. The scanner types into whatever browser window is in focus.

> **Note:** For a fixed scanning station (e.g., a dedicated tablet or laptop next to your bookshelf), you can plug the scanner directly into that device and point the browser at your server's IP address.

### Step 2 — Test the Scanner

1. Open Notepad (Windows), TextEdit (Mac), or any text editor
2. Click inside the text area
3. Scan a book's barcode
4. You should see a 13-digit number appear (e.g., `9780385737951`) followed by a new line

If you see the number, the scanner is working correctly.

### Step 3 — Open the Scan Page

1. Navigate to **http://your-server-ip:5000/scan** in your browser
2. The ISBN input field is auto-focused (you may see a blinking cursor)
3. Scan a book — the lookup fires automatically

### Step 4 — Confirm and Add

After each scan:
- Book details appear (cover, title, author, publisher)
- Select the family member who owns the book
- Choose the condition (New / Good / etc.) and optionally enter a shelf location
- Click **Add to Library**
- The input clears automatically, ready for the next book

---

## Configuring the Scanner (Honeywell Voyager 1200g)

The Voyager 1200g works out of the box. Optionally, you can scan the configuration barcodes in the user manual to:

- Enable/disable the Enter suffix (it's on by default — leave it on)
- Adjust the scan beep volume
- Switch to USB Serial mode (not needed for this app — keep it in HID mode)

The manual is available as a PDF at Honeywell's support site. Search for "Voyager 1200g Quick Start Guide."

---

## Wireless Scanner Setup (Inateck BCST-70)

1. Plug the USB dongle into the computer running the browser
2. Turn the scanner on (power switch on the side)
3. The scanner and dongle pair automatically
4. Follow the same test steps above

If the scanner and dongle lose pairing (e.g., after long storage):
1. Hold the trigger for 5 seconds until you hear a double beep
2. The dongle's LED will flash — the devices will re-pair

---

## Troubleshooting

### Scan does nothing / input doesn't fill in
- Make sure you clicked inside the ISBN input field first, or just click anywhere on the Scan page (the app will re-focus the input)
- Some browsers de-focus the input when you switch apps; just click back on the browser window

### Wrong characters appear (e.g., symbols instead of numbers)
- Your OS keyboard layout may differ from the scanner's expectation
- On Windows: go to Language Settings → ensure your input language is English (US)
- On Mac: System Preferences → Keyboard → Input Sources → ensure English is selected

### Scanner reads the book's UPC instead of ISBN
- Older books (pre-1970s) may only have a UPC. The app accepts 10 and 13 digit ISBNs. If the UPC doesn't look up correctly, use the manual entry option.

### "Book not found" for a valid ISBN
- Some books (especially self-published, academic, or non-English titles) aren't in Google Books or Open Library
- Use the **Add Manually** button on the error card to enter the details yourself

### Very old books with no barcode
- Look for the ISBN on the copyright page (usually starts with "ISBN" followed by 10 digits)
- Type it manually into the ISBN field and press Enter

---

## Multi-Device Scanning Tips

If multiple family members want to scan books simultaneously:

1. Each person opens the Scan page on their own device (phone, tablet, laptop)
2. Connect their scanner to their device via USB or wireless dongle
3. Each person selects their own name in the "Add for" selector
4. Books are added to each person's library independently

The app supports concurrent users — there's no locking or session conflicts.
