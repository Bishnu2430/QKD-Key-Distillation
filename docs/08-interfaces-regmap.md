# 08 — Interfaces and Register Map

| Version | 0.0 (outline), 21 Sep 2026 |
|---|---|
| Owner milestone | M4 (decoder), M6 (verification, PA) |

> **Outline.** Proposed register layout below; freeze at M4.

## 1. AXI4-Stream

| Stream | Direction | TDATA | Content per frame (packing per [05 §2](05-algorithm-spec.md#2-conventions)) |
|---|---|---|---|
| `s_axis_frame` | PS → PL | 64 bit | Header word, then $y$ ($n/64$ words), then $s$ ($m/64$ words); TLAST on the last word |
| `m_axis_key` | PL → PS | 64 bit | Header/status word, then $\hat{x}_{key}$; TLAST on the last word |
| `s_axis_pa` / `m_axis_pa` | PS ↔ PL | 64 bit | PA input block / seed / output (defined in M6) |

Header word fields (proposed): `frame_seq[31:0]`, `mask_id[7:0]`, `A[7:0]`, `flags[15:0]`.

## 2. AXI4-Lite register map (proposed)

**Base address: `0x4000_0000`**, assigned to `ldpc_axi_wrap_0/S_AXI` by the Address Editor in the stage-13 block design, with a 4 KB range. Every offset below is relative to it, so `STATUS` is at `0x4000_0008`.

This is the one number software cannot derive from anything else in the repository: it comes out of the block design, and it changes if the design is rebuilt with a different address assignment. Check it against the Address Editor before trusting it.

| Offset | Name | Access | Fields |
|---|---|---|---|
| 0x00 | `ID` | RO | Magic `0x514B4431` ("QKD1"), version |
| 0x04 | `CTRL` | RW | `start`, `soft_reset`, `irq_en` |
| 0x08 | `STATUS` | RO | `busy`, `done`, `err` |
| 0x0C | `IMAX` | RW | `i_max[5:0]` |
| 0x10 | `MASK_ID` | RW | Default mask if not in header |
| 0x14 | `CH_LLR_A` | RW | $A$ (default if not in header) |
| 0x18 | `LAST_ITERS` | RO | Iterations of the last frame |
| 0x1C | `FRAMES_OK` | RO | Counter |
| 0x20 | `FRAMES_FAIL` | RO | Counter |
| 0x24 | `CYCLES` | RO | Cycle counter (for on-chip throughput checks) |
| 0x40+ | PA / verification registers | — | Defined in M6 |

## 3. Error and status codes
To define: decode failure, stream framing error (TLAST in the wrong place), unsupported mask_id.
