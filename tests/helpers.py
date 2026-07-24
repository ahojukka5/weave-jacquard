from __future__ import annotations


def const(value: int, type_: str = "i32") -> dict:
    return {"kind": "const", "type": type_, "value": value}


def param(name: str) -> dict:
    return {"kind": "param", "name": name}


def local(name: str) -> dict:
    return {"kind": "local", "name": name}


def call(function: str, *args: dict) -> dict:
    return {"kind": "call", "function": function, "args": list(args)}


def binary(op: str, left: dict, right: dict) -> dict:
    return {"kind": "binary", "op": op, "left": left, "right": right}
