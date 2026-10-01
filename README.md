# JASS Jamabandi Native Edge Capture v3.0.0

Captures the **already-open, readable Jamabandi page displayed by Microsoft Edge**.

## Deliberate constraints

This version does **not**:
- print
- save to PDF
- download the Jamabandi
- use remote debugging
- use browser DevTools/site debugging
- reload the Jamabandi URL

It simply captures the pixels Edge is already displaying.

## Important

Keep the 86-page Jamabandi open in Edge and do not refresh or close the tab.

Because this is screen capture, output resolution is limited to the actual pixels displayed on the monitor. It does not invent higher-resolution source pixels.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Recommended workflow

1. Open the Jamabandi in Edge.
2. Make sure the page is readable.
3. Maximize Edge if possible.
4. Start this application.
5. Leave **Test mode** enabled.
6. Set the capture rectangle to contain only the Jamabandi page.
7. Capture the first 3 pages.
8. Inspect the PNGs.
9. If correct, disable Test mode and capture all 86 pages.

The program clicks inside Edge before each PageDown so PageDown is sent to the Jamabandi rather than to this application.
