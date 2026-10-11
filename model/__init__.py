"""L1 floating-point reference model for QKD key distillation.

Implements docs/05-algorithm-spec.md. Every module names the spec section it
implements; if the two ever disagree, the spec wins and the code is the bug.

Layout
------
``bits``      bit ordering and 64-bit packing (spec section 2)
``info``      entropy, efficiency, rate arithmetic
``code``      QC-LDPC representation, syndrome, rate masks (3.1 to 3.3, 3.5)
``frame``     Alice's word, BSC channel, Bob's initial LLRs (3.3, 3.4)
``decoder``   layered normalized min-sum syndrome decoder (3.6, 3.7)
``hashing``   Toeplitz verification tag and privacy amplification (4, 5)
``pipeline``  end-to-end frame and block processing, measurement helpers
"""

from . import bits, code, decoder, frame, hashing, info, pipeline  # noqa: F401

__all__ = ["bits", "code", "decoder", "frame", "hashing", "info", "pipeline"]
