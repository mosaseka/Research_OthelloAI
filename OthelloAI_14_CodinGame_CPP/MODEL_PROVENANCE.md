# Model provenance

## Width 16

- Source: `C:\Code\OthelloAI_11_CodinGame\model\param.txt`
- Source file SHA-256:
  `FF16C4D3D697B1F838985091648CE4ACD63E708F14A1A9F693E19AFFFC6AB6B1`
- Parameter count: 25,436
- Generated little-endian int16 CRC-32: `F681AF8C`
- Generated little-endian int16 SHA-256:
  `E1B447C3D58FD1BBBD2C4C82FBBA5F2DE89E8C4E91EFBF269A470B919921A94E`
- Quantization: one symmetric int16 scale per phase

## Width 48

- Source: `C:\Code\OthelloAI_final_48_CodinGame\model\param.txt`
- Source file SHA-256:
  `9FA0820F15356561F8A576F3C306B48F0043BBAA3782A838D2CC6105BBA1D15B`
- Parameter count: 142,812
- Quantization: one signed 11-bit scale per exported tensor (288 tensors)
- Container: binary32 scales plus little-endian int16 values, zlib-compressed,
  then packed into safe 15-bit BMP symbols

Regenerate candidate sources with the checked-in build scripts; do not edit an
embedded model literal manually.
