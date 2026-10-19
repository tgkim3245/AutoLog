"""Read local XL application mappings without opening a port or changing hardware."""

import ctypes
import json
import os
from pathlib import Path


def parse_baseline(value):
    if not value:
        return None
    if len(value) > 32768:
        raise ValueError("Hardware baseline is too large")
    document = json.loads(value)
    if not isinstance(document, dict) or set(document) != {"cfg", "application", "channels"}:
        raise ValueError("Invalid hardware baseline")
    if not isinstance(document["cfg"], str) or not isinstance(document["application"], str):
        raise ValueError("Invalid hardware baseline identity")
    channels = document["channels"]
    if not isinstance(channels, list) or not 1 <= len(channels) <= 64:
        raise ValueError("Invalid hardware baseline channels")
    for item in channels:
        if not isinstance(item, dict) or set(item) != {"logical", "hw_type", "serial", "port"}:
            raise ValueError("Invalid hardware baseline channel")
        if any(type(number) is not int or number < 0 for number in item.values()):
            raise ValueError("Invalid hardware baseline value")
    return document


def _xl_mapping(application, count):
    # Only driver inventory/configuration functions: no Bus(), port, activation or TX.
    from can.interfaces.vector import xlclass, xldriver
    if xldriver is None:
        raise RuntimeError("Vector XL driver library is unavailable")
    xldriver.xlOpenDriver()
    try:
        config = xlclass.XLdriverConfig()
        xldriver.xlGetDriverConfig(ctypes.byref(config))
        if not 0 <= config.channelCount <= len(config.channel):
            raise ValueError("Unsupported XL driver channel count")
        channels = []
        for logical in range(1, count + 1):
            hw_type, hw_index, hw_channel = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
            xldriver.xlGetApplConfig(application.encode("mbcs"), logical - 1,
                                    ctypes.byref(hw_type), ctypes.byref(hw_index),
                                    ctypes.byref(hw_channel), 1)  # XL_BUS_TYPE_CAN
            item = next((item for item in config.channel[:config.channelCount]
                         if (item.hwType, item.hwIndex, item.hwChannel) ==
                         (hw_type.value, hw_index.value, hw_channel.value)), None)
            if item is None:
                raise RuntimeError(f"CAN {logical}: mapped hardware is unavailable")
            channels.append({"logical": logical, "hw_type": int(item.hwType),
                             "serial": int(item.serialNumber), "port": int(item.hwChannel) + 1,
                             "name": bytes(item.name).decode("mbcs", errors="replace"),
                             "driver_version": int(item.driverVersion),
                             "physical": int(item.hwType) > 1 and int(item.serialNumber) > 0,
                             "config_error": int(item.configError)})
        return channels
    finally:
        xldriver.xlCloseDriver()


def inspect_hardware(app, cfg, baseline="", *, query=_xl_mapping):
    report = {"status": "unavailable", "channels": [], "application": "", "detail": "",
              "reference_required": bool(baseline),
              "scope": "local_xl_application_mapping_not_bus_reception"}
    try:
        count = int(app.Configuration.GeneralSetup.Channels(1))
        application = str(app.ChannelMappingName).strip()
        if not application or not 1 <= count <= 64:
            raise ValueError("CAN channel count or application mapping name is unavailable")
        report["application"] = application
        # Remote/VTP mappings cannot be inferred from this PC's local XL driver.
        if bool(app.Configuration.DistributedMode):
            raise ValueError("Distributed CANoe hardware must be checked on its target device")
        channels = query(application, count)
        report["channels"] = channels
        if len(channels) != count or any(not c["physical"] or c["config_error"] for c in channels):
            report["status"] = "unavailable"
            report["detail"] = "Virtual, missing or invalid hardware mapping"
            return report
        identity = {"cfg": str(Path(cfg).resolve()), "application": application,
                    "channels": [{k: c[k] for k in ("logical", "hw_type", "serial", "port")} for c in channels]}
        report["baseline"] = identity
        expected = parse_baseline(baseline)
        report["status"] = "unreferenced"
        if expected:
            same_cfg = os.path.normcase(os.path.abspath(expected["cfg"])) == os.path.normcase(identity["cfg"])
            report["status"] = "match" if same_cfg and expected["application"] == application and (
                expected["channels"] == identity["channels"]) else "mismatch"
    except Exception as error:
        report["status"] = "unavailable"
        report.pop("baseline", None)
        report["detail"] = str(error)
    return report
