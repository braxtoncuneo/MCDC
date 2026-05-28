import numpy as np

from dataclasses import dataclass, field
from typing import Annotated
from numpy import int64, uint64
from numpy.typing import NDArray

####

#from mcdc.constant import TRACE_SLOT_LIMIT
from mcdc.object_.base import ObjectSingleton, ObjectNonSingleton


#trace_slot = into_dtype([
#    ("runtime_total", int64, (3,)),
#    ("call_total", int64, (3,)),
#])
#
#trace = None
#def set_trace(trace_slot_limit: int64):
#    global trace
#    trace = into_dtype([
#        ("slots", trace_slot, trace_slot_limit),
#        ("slot_limit", int64),
#    ])

@dataclass
class TraceSlot(ObjectNonSingleton):
    runtime_total: Annotated[NDArray[int64], (3,)]
    call_total: Annotated[NDArray[int64], (3,)]
    label: str = "trace_slot"
    tag: str = ""

    def __init__(self, tag):
        super().__init__()
        self.tag = tag
        self.runtime_total = np.zeros(3, dtype=int64)
        self.call_total = np.zeros(3, dtype=int64)


class Trace(ObjectSingleton):
    label: str = "trace"
    slots: list[TraceSlot]
    slot_limit: Annotated[int64]
    tag: str = ""

    def __init__(self, tag):
        super().__init__()
        self.tag = tag
