# Local Modbus TCP Register Viewer

A small, read-only Tkinter application for viewing holding registers from a **local Modbus TCP simulator or service**. It uses Modbus Function Code 03 (Read Holding Registers), displays raw and tenths-scaled values, and stores successful samples in SQLite.

## Safety and scope

This version deliberately accepts only IPv4 loopback addresses in the `127.0.0.0/8` range. It cannot connect to a remote Modbus TCP device. Use it with a local simulator or another Modbus service that you are authorized to test.

The application issues only FC03 reads. It contains no Modbus write operations. The polling interval is 800 ms, and the requested register count is capped at 120 per poll.

## Requirements

- Python 3.10 or later
- A local Modbus TCP simulator/service listening on the configured loopback address and port
- `pymodbus`

Tkinter is included with most standard Python installations. On some Linux distributions, install the system Tk package if `import tkinter` fails.

## Run

1. Save `main.py` in a working directory.
2. Install the dependency:

   ```bash
   python -m pip install pymodbus
   ```

3. Start an authorized Modbus TCP simulator bound to a loopback address, such as `127.0.0.1`.
4. Run the application:

   ```bash
   python main.py
   ```

5. Enter the simulator's loopback IP, port, unit ID, starting register address, and number of registers. Click **Start Polling**. Click **Stop** to stop scheduling further polls.

Defaults are `127.0.0.1`, port `502`, unit ID `1`, start address `3000`, and `20` registers. The application retries on the next polling tick after a connection or Modbus error; it reports the error in the status line rather than terminating.

## Reading the memory map

The table shows the address, raw 16-bit integer, and a displayed value calculated as `raw / 10.0`. That scaling is an example convention, not a universal Modbus standard. Confirm the register map and scaling rules for the specific simulator or device being modeled.

To identify a parameter such as line speed or temperature:

1. Consult the equipment or simulator's register map for the parameter's holding-register address.
2. Set **Start Register Address** to that address, or choose a range that includes it.
3. Compare the raw register and displayed scaled value with the map's documented data type, units, scale factor, and signedness.
4. Treat the displayed `/ 10.0` result as meaningful only when the register documentation specifies that scale. Other parameters may require a different scale, signed interpretation, multiple registers, or a different Modbus function.

Register numbering conventions can differ between documentation and protocol addresses. Some maps use one-based reference numbers while the Modbus request uses a zero-based address; follow the simulator's documentation.

## History database

Successful polls are appended to `modbus_scan_history.db` in the current working directory. Each register sample includes a UTC timestamp, connection fields, register address, raw integer, and scaled float. The database is created automatically when the application starts.

## Build a standalone Windows executable

From a Windows command prompt in the directory containing `main.py` and `build.bat`, run:

```bat
build.bat
```

The script installs `pymodbus` and PyInstaller, then creates a single-file, console-free executable at:

```text
dist\main.exe
```

The executable still requires a local Modbus TCP simulator/service to provide register data. The SQLite database is created in the executable's working directory.
