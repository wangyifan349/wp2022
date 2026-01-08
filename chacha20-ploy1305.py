"""
这个工具的工作流程分成“输入交互 → 递归遍历 → 对每个文件按固定容器格式流式处理”三层。程序启动后会询问用户选择加密还是解密（E/D），随后用隐藏输入读取用户密码：如果是加密会要求二次确认以避免输错；接着用户输入一个“源路径”（可以是单个文件或一个目录）以及一个“输出目录”。当源路径是目录时，程序会做一个安全检查：禁止输出目录落在源目录内部（否则会把新生成的加密文件再次被 os.walk 扫到，导致递归处理/重复加密）。最终程序会根据你选的模式调用加密或解密入口，对文件或目录树进行处理，并把结果按相对路径结构写入输出目录中。
加密时，每个文件都会被写成一个独立的二进制容器文件（后缀 `.cc20p13c`），并且采用“分块（chunk）流式”的方式处理大文件：先写入文件头（header），再循环读取明文分块、加密并写出记录（record），直到 EOF。文件头固定以 `MAGIC="CC20P13C"` 开头，版本号 `VERSION=3`，并包含：`FLAGS`（bit0=1 表示本文件使用密码派生密钥）、`CHUNK_SIZE`（4字节小端，默认 1,048,576）、`BASE_NONCE`（12字节随机），以及 KDF 信息：`KDF_ID=1`（PBKDF2-HMAC-SHA256）、`ITER`（4字节小端，默认 300000）、`SALT_LEN=16` 与 `SALT`（16字节随机）。密钥派生规则是：将用户密码按 UTF-8 编码成字节串，使用 `PBKDF2-HMAC-SHA256(password_utf8, SALT, ITER, dkLen=32)` 得到 32 字节对称密钥。随后对第 i 个分块（i 从 0 开始递增），计算每块 nonce：`mask = LE32(i) || 0x00*8`（12字节），`record_nonce = BASE_NONCE XOR mask`。每块加密用 RFC 8439 ChaCha20-Poly1305：AAD 固定为空 `AD=b""`，一次性 Poly1305 密钥 `OTK` 取 `ChaCha20_Block(key, counter=0, nonce=record_nonce)` 的前 32 字节，密文 `CT = ChaCha20_XOR(key, counter=1, nonce=record_nonce, P)`，认证数据 `mac_data = AD||pad16(AD)||CT||pad16(CT)||le64(len(AD))||le64(len(CT))`（由于 AD 为空，可化简为 `CT||pad16(CT)||le64(0)||le64(len(CT))`），标签 `TAG = Poly1305(mac_data, OTK)` 得到 16 字节。写盘时每个 record 的格式是：`PLAINTEXT_LEN(4字节小端)` + `CIPHERTEXT(PLAINTEXT_LEN字节)` + `TAG(16字节)`，其中 `PLAINTEXT_LEN` 允许小于 `CHUNK_SIZE`（用于最后一块）。
解密时流程与加密严格对称：程序从 `.cc20p13c` 文件读取并校验 header（检查 MAGIC、VERSION、FLAGS、KDF_ID、SALT_LEN 等），再用 header 中的 `SALT` 与 `ITER` 对用户输入密码做相同的 PBKDF2 派生，得到同一把 32 字节密钥。然后从文件体开始按 record 读取：先读 4 字节得到 `PLAINTEXT_LEN`，再读对应长度的 `CIPHERTEXT` 与随后的 16 字节 `TAG`，用相同的 `record_index` 计算 `record_nonce`，先按 RFC 8439 规则重算期望的 `TAG` 并做常量时间比较；若认证失败则立即报错（表示密码不对或文件被篡改/损坏），若认证通过则执行 `P = ChaCha20_XOR(key, counter=1, nonce=record_nonce, CIPHERTEXT)` 得到明文分块并顺序写入输出文件。对于目录解密，程序会递归扫描所有以 `.cc20p13c` 结尾的文件并在输出目录中保持相对路径结构，默认将输出文件名去掉 `.cc20p13c` 后缀；这样你未来在任何语言中只要实现：PBKDF2-HMAC-SHA256、RFC8439 ChaCha20-Poly1305、相同的 nonce 派生与容器读写规则，就可以完整重实现加密与解密并互通。
"""
"""
整体工作流程分为交互层、路径遍历层、文件容器读写层三部分。交互层：程序启动后要求用户选择模式（E=加密，D=解密），然后通过隐藏输入读取用户密码；若是加密模式会再次要求输入同一密码用于确认，避免口令输错导致将来无法解密。随后用户输入“源路径”和“输出目录”：源路径可以是单个文件或目录；当源路径为目录时，程序递归遍历目录树（等价于 Python 的 os.walk），对其中每一个普通文件执行加密/解密，并把生成文件写到输出目录下，保持与源目录相同的相对路径结构。为了避免在源目录内部生成输出文件又被递归扫描到造成重复处理，程序应拒绝“输出目录位于源目录内部”的情况。路径映射规则必须固定：加密时输出文件名为“原文件相对路径 + 字符串后缀 .cc20p13c”；解密时仅处理以 .cc20p13c 结尾的文件，输出文件名为“相对路径去掉后缀 .cc20p13c”（若某实现允许解密单文件且输入不带该后缀，则输出名可附加 .dec 作为兜底，但目录批量解密建议严格要求后缀匹配以防误处理）。
加密文件采用一个自定义的二进制容器格式 CC20P13C，版本号为 3，设计目标是可流式处理超大文件且跨语言可复现。一个加密文件由“文件头 Header + 多条记录 Records”组成；Records 逐条顺序存储，每条记录对应一个明文分块（chunk）。Header 字节布局必须精确如下（所有整数均为小端 little-endian）：MAGIC 为 8 字节 ASCII 字面量“CC20P13C”；VERSION 为 1 字节，固定值 0x03；FLAGS 为 1 字节，bit0=1 表示启用密码派生密钥（本工具始终为 1）；CHUNK_SIZE 为 4 字节无符号整数 uint32，表示每个明文分块最大长度（默认 1048576，即 1MiB）；BASE_NONCE 为 12 字节随机值；随后是 KDF 参数段：KDF_ID 为 1 字节，固定值 0x01 表示 PBKDF2-HMAC-SHA256；ITER 为 4 字节 uint32（默认 300000）；SALT_LEN 为 1 字节，固定值 16；SALT 为 16 字节随机值。密钥派生规则必须保持一致：将用户密码按 UTF-8 编码得到 password_bytes，然后计算 key = PBKDF2-HMAC-SHA256(password_bytes, SALT, ITER, dkLen=32)，输出长度固定 32 字节。加密正文部分由若干 Records 构成，每条 Record 布局为：PLAINTEXT_LEN（4 字节 uint32） + CIPHERTEXT（PLAINTEXT_LEN 字节） + TAG（16 字节）。其中 PLAINTEXT_LEN 取值范围为 1..CHUNK_SIZE；最后一块通常小于 CHUNK_SIZE。分块加密算法为 RFC 8439 ChaCha20-Poly1305（IETF 96-bit nonce 变体），并且 AAD（Associated Data）固定为空字节串 AD = ""。每条记录都有独立 nonce：record_index 从 0 开始递增（每写一条记录加 1，按 uint32 溢出语义，但实际文件不应接近 2^32 条记录）；计算 mask = LE32(record_index) || 0x00*8（合计 12 字节），record_nonce = BASE_NONCE XOR mask（逐字节 XOR）。随后按 RFC 8439：一次性 Poly1305 密钥 OTK 取 ChaCha20_Block(key, counter=0, nonce=record_nonce) 的前 32 字节；密文 CT = ChaCha20_XOR(key, counter=1, nonce=record_nonce, plaintext)；认证输入 mac_data = AD || pad16(AD) || CT || pad16(CT) || le64(len(AD)) || le64(len(CT))，其中 pad16(x) 表示将长度填充到 16 的倍数所需的 0x00 字节（若本身为 16 的倍数则不填充），le64 为 8 字节小端无符号整数。由于 AD 固定为空，可化简为 mac_data = CT || pad16(CT) || le64(0) || le64(len(CT))。TAG = Poly1305(mac_data, OTK)，输出 16 字节并原样写入文件。跨语言实现时必须注意：ChaCha20 的 state 常量为“expand 32-byte k”，counter 为 32-bit，nonce 为 96-bit（12 字节），序列化/反序列化均为小端；Poly1305 的 r 需按规范 clamp；TAG 比较应使用常量时间比较以减少侧信道。
解密流程必须与上述规则逐字节对称，且要把“认证失败”视为致命错误以保证安全与正确性。解密时先读取并验证 Header：MAGIC 必须匹配“CC20P13C”，VERSION 必须为 3；FLAGS 的 bit0 必须为 1；KDF_ID 必须为 1；SALT_LEN 必须为 16；并读取 CHUNK_SIZE、BASE_NONCE、ITER、SALT。然后使用同样的 UTF-8 编码与 PBKDF2-HMAC-SHA256 规则派生出 32 字节 key。随后从文件当前位置开始循环读取 Records：先读 4 字节得到 PLAINTEXT_LEN，若读到 EOF 则正常结束；若不足 4 字节则表示文件截断；若 PLAINTEXT_LEN 为 0 或大于 CHUNK_SIZE 则视为格式错误；再读取 PLAINTEXT_LEN 字节密文与 16 字节 TAG，任何不足都视为截断错误。对第 record_index 条记录，用同样的 mask 与 XOR 规则计算 record_nonce；然后按 RFC 8439 重新计算 expected_tag（使用相同的 AD=""、相同的 mac_data 构造与 Poly1305），若 expected_tag 与读到的 TAG 不一致，则必须立即报错并停止（通常原因是密码错误、文件被篡改、或数据损坏），不得输出任何未认证的明文。若认证通过，再执行 plaintext = ChaCha20_XOR(key, counter=1, nonce=record_nonce, ciphertext) 得到明文分块并顺序写入输出文件，record_index 自增继续下一条记录。这样做可以保证：只要保存了加密文件本身以及用户密码（并且 Header 未被破坏到无法读取 SALT/ITER），未来用任何语言重新实现 PBKDF2-HMAC-SHA256 和 RFC 8439 ChaCha20-Poly1305，并严格遵守本容器的字节布局、端序、nonce 派生与 record 读取规则，就能够稳定地完成解密并与当前实现互通。
"""
from __future__ import annotations

import os
import struct
import hashlib
import getpass
from dataclasses import dataclass
from typing import Tuple
# ============================================================
# CC20P13C v3 (password-based, chunked, streaming)
#
# Purpose:
#   - Encrypt/decrypt very large files (10GB+) without loading them into memory
#   - Support encrypting/decrypting a directory recursively (os.walk)
#   - Use a user password (PBKDF2-HMAC-SHA256) so key material can be recreated later
#
# Crypto design:
#   - Each chunk is encrypted and authenticated using RFC 8439 ChaCha20-Poly1305
#   - Each chunk uses a unique nonce derived from a random base nonce + record index
#   - AAD (associated data) is fixed to empty (b"") to keep format stable
#
# File format (binary) overview:
#   Header:
#     MAGIC(8) = "CC20P13C"
#     VERSION(1) = 3
#     FLAGS(1) = bit0 means "password-KDF present"
#     CHUNK_SIZE(4 LE)
#     BASE_NONCE(12)
#     KDF_ID(1) = 1 (PBKDF2-HMAC-SHA256)
#     ITER(4 LE)
#     SALT_LEN(1) = 16
#     SALT(16)
#   Records (repeat until EOF):
#     PLAINTEXT_LEN(4 LE)
#     CIPHERTEXT(PLAINTEXT_LEN)
#     TAG(16)
# ============================================================

MAGIC = b"CC20P13C"      # 8 bytes marker used to identify this file type
VERSION = 3              # version of this container format

FLAG_PASSWORD_KDF = 0x01
KDF_ID_PBKDF2_SHA256 = 0x01

KEY_SIZE = 32
NONCE_SIZE = 12
TAG_SIZE = 16
CHACHA_BLOCK_SIZE = 64

DEFAULT_CHUNK_SIZE = 1024 * 1024     # 1 MiB per record (good balance for speed/overhead)
DEFAULT_PBKDF2_ITERATIONS = 300_000   # increase if you want slower brute-force
DEFAULT_SALT_LENGTH = 16             # salt stored in header, must stay fixed for compatibility


# ============================================================
# KDF: password -> 32-byte key
# ============================================================

def derive_key_from_password(password: str, salt: bytes, iterations: int) -> bytes:
    # The password is converted to UTF-8 bytes (important for cross-language compatibility)
    if password is None or password == "":
        raise ValueError("Password must be non-empty.")
    if iterations <= 0 or iterations > 0xFFFFFFFF:
        raise ValueError("PBKDF2 iterations out of range.")
    if salt is None or len(salt) < 8:
        raise ValueError("Salt too short.")

    password_bytes = password.encode("utf-8")
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password_bytes,
        salt,
        iterations,
        dklen=KEY_SIZE
    )
    return key


# ============================================================
# Small utilities
# ============================================================

def ensure_parent_directory(file_path: str) -> None:
    # Create parent folder if needed (so writing output won't fail)
    parent_dir = os.path.dirname(file_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

def is_encrypted_file(file_path: str) -> bool:
    # Used for directory scanning / suffix checks
    lower_name = file_path.lower()
    return lower_name.endswith(".cc20p13c")

def constant_time_equals(left: bytes, right: bytes) -> bool:
    # Constant-time equality check to reduce timing side channels on tag compare
    if len(left) != len(right):
        return False
    diff = 0
    index = 0
    while index < len(left):
        diff |= left[index] ^ right[index]
        index += 1
    return diff == 0

def pad16(length: int) -> bytes:
    # RFC 8439 uses padding to 16-byte blocks for Poly1305 MAC input construction
    remainder = length % 16
    if remainder == 0:
        return b""
    return b"\x00" * (16 - remainder)

def pack_u32_le(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)

def pack_u64_le(value: int) -> bytes:
    return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)

def load_u32_le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]

def rotate_left_u32(value: int, bits: int) -> int:
    # 32-bit left rotation used by ChaCha20
    value = value & 0xFFFFFFFF
    return ((value << bits) & 0xFFFFFFFF) | (value >> (32 - bits))


# ============================================================
# ChaCha20 (RFC 8439, IETF nonce layout)
# ============================================================

def chacha20_quarter_round(a: int, b: int, c: int, d: int) -> Tuple[int, int, int, int]:
    # Standard ChaCha quarter round
    a = (a + b) & 0xFFFFFFFF
    d = d ^ a
    d = rotate_left_u32(d, 16)

    c = (c + d) & 0xFFFFFFFF
    b = b ^ c
    b = rotate_left_u32(b, 12)

    a = (a + b) & 0xFFFFFFFF
    d = d ^ a
    d = rotate_left_u32(d, 8)

    c = (c + d) & 0xFFFFFFFF
    b = b ^ c
    b = rotate_left_u32(b, 7)

    return a, b, c, d

def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    # Produces one 64-byte ChaCha20 keystream block.
    # State:
    #   0..3 constants, 4..11 key, 12 counter, 13..15 nonce (96-bit)
    if key is None or len(key) != KEY_SIZE:
        raise ValueError("Key must be 32 bytes.")
    if nonce is None or len(nonce) != NONCE_SIZE:
        raise ValueError("Nonce must be 12 bytes.")

    state = [0] * 16

    # "expand 32-byte k"
    state[0] = 0x61707865
    state[1] = 0x3320646e
    state[2] = 0x79622d32
    state[3] = 0x6b206574

    i = 0
    while i < 8:
        state[4 + i] = load_u32_le(key, 4 * i)
        i += 1

    state[12] = counter & 0xFFFFFFFF
    state[13] = load_u32_le(nonce, 0)
    state[14] = load_u32_le(nonce, 4)
    state[15] = load_u32_le(nonce, 8)

    working = state.copy()

    # 20 rounds = 10 double-rounds
    round_index = 0
    while round_index < 10:
        # column rounds
        working[0], working[4], working[8], working[12] = chacha20_quarter_round(working[0], working[4], working[8], working[12])
        working[1], working[5], working[9], working[13] = chacha20_quarter_round(working[1], working[5], working[9], working[13])
        working[2], working[6], working[10], working[14] = chacha20_quarter_round(working[2], working[6], working[10], working[14])
        working[3], working[7], working[11], working[15] = chacha20_quarter_round(working[3], working[7], working[11], working[15])

        # diagonal rounds
        working[0], working[5], working[10], working[15] = chacha20_quarter_round(working[0], working[5], working[10], working[15])
        working[1], working[6], working[11], working[12] = chacha20_quarter_round(working[1], working[6], working[11], working[12])
        working[2], working[7], working[8], working[13] = chacha20_quarter_round(working[2], working[7], working[8], working[13])
        working[3], working[4], working[9], working[14] = chacha20_quarter_round(working[3], working[4], working[9], working[14])

        round_index += 1

    # Add original state (feed-forward)
    output_words = [0] * 16
    word_index = 0
    while word_index < 16:
        output_words[word_index] = (working[word_index] + state[word_index]) & 0xFFFFFFFF
        word_index += 1

    # Serialize to bytes little-endian
    output_bytes = bytearray()
    word_index = 0
    while word_index < 16:
        output_bytes += pack_u32_le(output_words[word_index])
        word_index += 1

    return bytes(output_bytes)

def chacha20_xor(key: bytes, nonce: bytes, initial_counter: int, data: bytes) -> bytes:
    # Encrypt/decrypt by XORing data with ChaCha20 keystream.
    # For RFC 8439 AEAD, encryption uses counter=1 (counter=0 used for Poly1305 key).
    output = bytearray(len(data))
    counter = initial_counter & 0xFFFFFFFF
    offset = 0

    while offset < len(data):
        keystream = chacha20_block(key, counter, nonce)
        counter = (counter + 1) & 0xFFFFFFFF

        bytes_remaining = len(data) - offset
        block_bytes = CHACHA_BLOCK_SIZE
        if bytes_remaining < block_bytes:
            block_bytes = bytes_remaining

        i = 0
        while i < block_bytes:
            output[offset + i] = data[offset + i] ^ keystream[i]
            i += 1

        offset += block_bytes

    return bytes(output)


# ============================================================
# Poly1305 + RFC 8439 AEAD
# ============================================================

def poly1305_one_time_key(key: bytes, nonce: bytes) -> bytes:
    # OTK = first 32 bytes of ChaCha20 block with counter=0
    block0 = chacha20_block(key, 0, nonce)
    return block0[0:32]

def poly1305_mac(message: bytes, one_time_key: bytes) -> bytes:
    # Computes Poly1305 tag over message using one-time key
    if one_time_key is None or len(one_time_key) != 32:
        raise ValueError("Poly1305 one-time key must be 32 bytes.")

    r = int.from_bytes(one_time_key[0:16], "little")
    s = int.from_bytes(one_time_key[16:32], "little")

    # clamp r per Poly1305
    r = r & 0x0ffffffc0ffffffc0ffffffc0fffffff

    p = (1 << 130) - 5
    acc = 0

    offset = 0
    while offset < len(message):
        block = message[offset:offset + 16]
        n = int.from_bytes(block, "little") + (1 << (8 * len(block)))
        acc = (acc + n) % p
        acc = (acc * r) % p
        offset += 16

    tag_int = (acc + s) & ((1 << 128) - 1)
    return tag_int.to_bytes(16, "little")

def aead_encrypt_rfc8439(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> Tuple[bytes, bytes]:
    # RFC 8439 AEAD:
    #   ciphertext = ChaCha20(key, counter=1, nonce) XOR plaintext
    #   tag = Poly1305(AD||pad16||CT||pad16||len(AD)||len(CT), OTK)
    one_time_key = poly1305_one_time_key(key, nonce)
    ciphertext = chacha20_xor(key, nonce, 1, plaintext)

    mac_data = bytearray()
    mac_data += aad
    mac_data += pad16(len(aad))
    mac_data += ciphertext
    mac_data += pad16(len(ciphertext))
    mac_data += pack_u64_le(len(aad))
    mac_data += pack_u64_le(len(ciphertext))

    tag = poly1305_mac(bytes(mac_data), one_time_key)
    return ciphertext, tag

def aead_decrypt_rfc8439(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes) -> bytes:
    # Verify tag first; only output plaintext if authentication succeeds
    if tag is None or len(tag) != TAG_SIZE:
        raise ValueError("Tag must be 16 bytes.")

    one_time_key = poly1305_one_time_key(key, nonce)

    mac_data = bytearray()
    mac_data += aad
    mac_data += pad16(len(aad))
    mac_data += ciphertext
    mac_data += pad16(len(ciphertext))
    mac_data += pack_u64_le(len(aad))
    mac_data += pack_u64_le(len(ciphertext))

    expected_tag = poly1305_mac(bytes(mac_data), one_time_key)
    if not constant_time_equals(expected_tag, tag):
        raise ValueError("Authentication failed (wrong password or corrupted data).")

    plaintext = chacha20_xor(key, nonce, 1, ciphertext)
    return plaintext


# ============================================================
# Record nonce derivation
# ============================================================

def derive_record_nonce(base_nonce: bytes, record_index: int) -> bytes:
    # Each record uses a derived nonce to avoid nonce reuse.
    # record_nonce = base_nonce XOR (LE32(record_index) || 0x00*8)
    if base_nonce is None or len(base_nonce) != NONCE_SIZE:
        raise ValueError("Base nonce must be 12 bytes.")
    if record_index < 0 or record_index > 0xFFFFFFFF:
        raise ValueError("Record index out of range (uint32).")

    mask = struct.pack("<I", record_index) + (b"\x00" * 8)
    output = bytearray(NONCE_SIZE)

    i = 0
    while i < NONCE_SIZE:
        output[i] = base_nonce[i] ^ mask[i]
        i += 1

    return bytes(output)


# ============================================================
# Header (v3): includes KDF params so decryption can be reproduced later
# ============================================================

@dataclass(frozen=True)
class HeaderV3:
    flags: int
    chunk_size: int
    base_nonce: bytes
    kdf_id: int
    pbkdf2_iterations: int
    salt: bytes

def read_exact(file_obj, size: int) -> bytes:
    data = file_obj.read(size)
    if len(data) != size:
        raise ValueError("Truncated file.")
    return data

def write_header_v3_password(file_obj, chunk_size: int, base_nonce: bytes, pbkdf2_iterations: int, salt: bytes) -> None:
    # Header is written once per file. The salt and iterations are stored here.
    if len(base_nonce) != NONCE_SIZE:
        raise ValueError("base_nonce length invalid.")
    if len(salt) != DEFAULT_SALT_LENGTH:
        raise ValueError("salt length invalid.")
    if pbkdf2_iterations <= 0 or pbkdf2_iterations > 0xFFFFFFFF:
        raise ValueError("pbkdf2_iterations out of range.")

    flags = FLAG_PASSWORD_KDF

    file_obj.write(MAGIC)
    file_obj.write(struct.pack("B", VERSION))
    file_obj.write(struct.pack("B", flags))
    file_obj.write(struct.pack("<I", chunk_size))
    file_obj.write(base_nonce)

    file_obj.write(struct.pack("B", KDF_ID_PBKDF2_SHA256))
    file_obj.write(struct.pack("<I", pbkdf2_iterations))
    file_obj.write(struct.pack("B", len(salt)))
    file_obj.write(salt)

def read_header_v3_password(file_obj) -> HeaderV3:
    # Parse and validate header fields; returns a HeaderV3 object.
    magic = read_exact(file_obj, 8)
    if magic != MAGIC:
        raise ValueError("Bad magic (not a CC20P13C file).")

    version = struct.unpack("B", read_exact(file_obj, 1))[0]
    if version != VERSION:
        raise ValueError("Unsupported version: %d" % version)

    flags = struct.unpack("B", read_exact(file_obj, 1))[0]
    chunk_size = struct.unpack("<I", read_exact(file_obj, 4))[0]
    base_nonce = read_exact(file_obj, NONCE_SIZE)

    if (flags & FLAG_PASSWORD_KDF) == 0:
        raise ValueError("This tool expects password-KDF files, but flag is not set.")

    kdf_id = struct.unpack("B", read_exact(file_obj, 1))[0]
    if kdf_id != KDF_ID_PBKDF2_SHA256:
        raise ValueError("Unsupported KDF id: %d" % kdf_id)

    pbkdf2_iterations = struct.unpack("<I", read_exact(file_obj, 4))[0]

    salt_len = struct.unpack("B", read_exact(file_obj, 1))[0]
    if salt_len != DEFAULT_SALT_LENGTH:
        raise ValueError("Unsupported salt length: %d" % salt_len)

    salt = read_exact(file_obj, salt_len)

    header = HeaderV3(
        flags=flags,
        chunk_size=chunk_size,
        base_nonce=base_nonce,
        kdf_id=kdf_id,
        pbkdf2_iterations=pbkdf2_iterations,
        salt=salt
    )
    return header


# ============================================================
# File encryption/decryption (password mode)
# ============================================================

def encrypt_file_password(
    input_file_path: str,
    output_file_path: str,
    password: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    pbkdf2_iterations: int = DEFAULT_PBKDF2_ITERATIONS
) -> None:
    # Encrypt a single file in a streaming way: read chunk -> encrypt -> write record.
    aad = b""  # fixed empty AAD for format stability
    base_nonce = os.urandom(NONCE_SIZE)
    salt = os.urandom(DEFAULT_SALT_LENGTH)
    key = derive_key_from_password(password, salt, pbkdf2_iterations)

    ensure_parent_directory(output_file_path)

    with open(input_file_path, "rb") as input_file:
        with open(output_file_path, "wb") as output_file:
            write_header_v3_password(output_file, chunk_size, base_nonce, pbkdf2_iterations, salt)

            record_index = 0
            while True:
                plaintext_chunk = input_file.read(chunk_size)
                if plaintext_chunk == b"":
                    break

                record_nonce = derive_record_nonce(base_nonce, record_index)
                ciphertext_chunk, tag = aead_encrypt_rfc8439(key, record_nonce, plaintext_chunk, aad)

                # Record layout: plaintext_len + ciphertext + tag
                output_file.write(struct.pack("<I", len(plaintext_chunk)))
                output_file.write(ciphertext_chunk)
                output_file.write(tag)

                record_index = (record_index + 1) & 0xFFFFFFFF

def decrypt_file_password(input_file_path: str, output_file_path: str, password: str) -> None:
    # Decrypt a single file: read header -> derive key -> read records -> verify -> write plaintext.
    aad = b""
    ensure_parent_directory(output_file_path)

    with open(input_file_path, "rb") as input_file:
        with open(output_file_path, "wb") as output_file:
            header = read_header_v3_password(input_file)
            key = derive_key_from_password(password, header.salt, header.pbkdf2_iterations)

            record_index = 0
            while True:
                length_bytes = input_file.read(4)
                if len(length_bytes) == 0:
                    break
                if len(length_bytes) != 4:
                    raise ValueError("Truncated file (record length).")

                plaintext_len = struct.unpack("<I", length_bytes)[0]
                if plaintext_len == 0:
                    raise ValueError("Invalid record length: 0")
                if plaintext_len > header.chunk_size:
                    raise ValueError("Invalid record length (exceeds chunk_size).")

                ciphertext = input_file.read(plaintext_len)
                if len(ciphertext) != plaintext_len:
                    raise ValueError("Truncated file (ciphertext).")

                tag = input_file.read(TAG_SIZE)
                if len(tag) != TAG_SIZE:
                    raise ValueError("Truncated file (tag).")

                record_nonce = derive_record_nonce(header.base_nonce, record_index)
                plaintext = aead_decrypt_rfc8439(key, record_nonce, ciphertext, tag, aad)
                output_file.write(plaintext)

                record_index = (record_index + 1) & 0xFFFFFFFF
# ============================================================
# Directory processing (os.walk)
# ============================================================
def encrypt_path_password(
    source_path: str,
    output_directory: str,
    password: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    pbkdf2_iterations: int = DEFAULT_PBKDF2_ITERATIONS
) -> None:
    # Encrypt a file or an entire directory tree.
    # If source_path is directory, we preserve relative paths under output_directory.
    source_path = os.path.abspath(source_path)
    output_directory = os.path.abspath(output_directory)

    os.makedirs(output_directory, exist_ok=True)

    if os.path.isfile(source_path):
        output_file_path = os.path.join(output_directory, os.path.basename(source_path) + ".cc20p13c")
        encrypt_file_password(source_path, output_file_path, password, chunk_size, pbkdf2_iterations)
        return

    if not os.path.isdir(source_path):
        raise ValueError("Source not found: %s" % source_path)

    for root, directory_names, file_names in os.walk(source_path):
        for file_name in file_names:
            input_file_path = os.path.join(root, file_name)
            if not os.path.isfile(input_file_path):
                continue
            relative_path = os.path.relpath(input_file_path, source_path)
            output_file_path = os.path.join(output_directory, relative_path + ".cc20p13c")
            encrypt_file_password(input_file_path, output_file_path, password, chunk_size, pbkdf2_iterations)
def decrypt_path_password(
    source_path: str,
    output_directory: str,
    password: str,
    strip_suffix: str = ".cc20p13c"
) -> None:
    # Decrypt a file or directory tree of ".cc20p13c" files.
    # Decrypted files will have the ".cc20p13c" suffix removed.
    source_path = os.path.abspath(source_path)
    output_directory = os.path.abspath(output_directory)
    os.makedirs(output_directory, exist_ok=True)
    if os.path.isfile(source_path):
        base_name = os.path.basename(source_path)
        if base_name.lower().endswith(strip_suffix):
            output_name = base_name[:-len(strip_suffix)]
        else:
            output_name = base_name + ".dec"
        output_file_path = os.path.join(output_directory, output_name)
        decrypt_file_password(source_path, output_file_path, password)
        return

    if not os.path.isdir(source_path):
        raise ValueError("Source not found: %s" % source_path)

    for root, directory_names, file_names in os.walk(source_path):
        for file_name in file_names:
            if not file_name.lower().endswith(strip_suffix):
                continue

            input_file_path = os.path.join(root, file_name)
            if not os.path.isfile(input_file_path):
                continue

            relative_path = os.path.relpath(input_file_path, source_path)

            if relative_path.lower().endswith(strip_suffix):
                relative_output_path = relative_path[:-len(strip_suffix)]
            else:
                relative_output_path = relative_path + ".dec"

            output_file_path = os.path.join(output_directory, relative_output_path)
            decrypt_file_password(input_file_path, output_file_path, password)
# ============================================================
# Interactive CLI helpers
# ============================================================
def prompt_path(prompt_text: str) -> str:
    # Accepts paths with optional quotes (Windows-friendly)
    value = input(prompt_text)
    value = value.strip()
    value = value.strip('"')
    return value
def is_subpath(parent_path: str, candidate_path: str) -> bool:
    # Returns True if candidate_path is inside parent_path (to avoid output-in-source recursion)
    parent_abs = os.path.abspath(parent_path)
    candidate_abs = os.path.abspath(candidate_path)
    try:
        common = os.path.commonpath([parent_abs, candidate_abs])
    except ValueError:
        return False
    return common == parent_abs
# ============================================================
# Main interactive entry point
# ============================================================
def main() -> None:
    print("CC20P13C (ChaCha20-Poly1305) Interactive Tool")
    print("Choose mode: Encrypt(E) or Decrypt(D)")

    mode = input("Mode (E/D): ").strip().lower()
    if mode != "e" and mode != "d":
        print("Invalid mode.")
        return

    # Password input is hidden
    password = getpass.getpass("Password: ")
    if password == "":
        print("Empty password is not allowed.")
        return

    # For encryption, confirm password to prevent accidental typos
    if mode == "e":
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.")
            return

    source_path = prompt_path("Source path (file or directory): ")
    if not os.path.exists(source_path):
        print("Source does not exist.")
        return

    output_directory = prompt_path("Output directory: ")
    if output_directory == "":
        print("Output directory is required.")
        return
    source_abs = os.path.abspath(source_path)
    output_abs = os.path.abspath(output_directory)
    # Safety check: do not allow output directory inside the source directory
    # because it would cause recursive processing / re-encrypting outputs.
    if os.path.isdir(source_abs):
        if is_subpath(source_abs, output_abs):
            print("Refusing to run because output directory is inside source directory.")
            print("Source: %s" % source_abs)
            print("Output: %s" % output_abs)
            return
    try:
        if mode == "e":
            encrypt_path_password(source_abs, output_abs, password)
            print("Encryption complete.")
        else:
            decrypt_path_password(source_abs, output_abs, password)
            print("Decryption complete.")
    except Exception as exc:
        print("ERROR: %s" % str(exc))
if __name__ == "__main__":
    main()
