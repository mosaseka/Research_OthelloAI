// Egaroucid v0002 transcript -> sampled policy-teacher shards.
// C++17, standard library only. Raw Egaroucid data is read but never changed.

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <variant>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr std::uint64_t kHorizontalMask = 0x7e7e7e7e7e7e7e7eULL;
constexpr std::uint64_t kFull = ~0ULL;
constexpr const char* kFeatureSchema = "exact-mobility-v1";
constexpr const char* kSampleHashAlgorithm = "fnv1a64-canonical-d4-v1";
constexpr const char* kSplitAlgorithm = "sha256-canonical-d4-board-v1";
constexpr const char* kSplitUnit = "canonical_d4_relative_board";
constexpr const char* kSplitMaterialPrefix = "Egaroucid-v0002-split";
const std::array<const char*, 3> kSplitNames = {"train", "val", "test"};

struct Error : std::runtime_error {
  using std::runtime_error::runtime_error;
};

// This parser and SHA-256 implementation are the same small, dependency-free
// primitives used by the verified original_05 v2 converter. Keeping the
// manifest and raw-source verification inside this process avoids trusting a
// filename/count-only proxy for the upstream conversion receipt.
class Json {
 public:
  using Array = std::vector<Json>;
  using Object = std::map<std::string, Json>;
  using Value = std::variant<std::nullptr_t, bool, std::int64_t, double,
                             std::string, Array, Object>;

  Json() : value_(nullptr) {}
  Json(std::nullptr_t) : value_(nullptr) {}
  Json(bool value) : value_(value) {}
  Json(std::int64_t value) : value_(value) {}
  Json(double value) : value_(value) {}
  Json(std::string value) : value_(std::move(value)) {}
  Json(Array value) : value_(std::move(value)) {}
  Json(Object value) : value_(std::move(value)) {}

  bool is_int() const { return std::holds_alternative<std::int64_t>(value_); }
  bool is_string() const { return std::holds_alternative<std::string>(value_); }
  bool is_array() const { return std::holds_alternative<Array>(value_); }
  bool is_object() const { return std::holds_alternative<Object>(value_); }

  std::int64_t as_int() const {
    if (!is_int()) throw Error("JSON value is not an integer");
    return std::get<std::int64_t>(value_);
  }
  const std::string& as_string() const {
    if (!is_string()) throw Error("JSON value is not a string");
    return std::get<std::string>(value_);
  }
  const Array& as_array() const {
    if (!is_array()) throw Error("JSON value is not an array");
    return std::get<Array>(value_);
  }
  const Object& as_object() const {
    if (!is_object()) throw Error("JSON value is not an object");
    return std::get<Object>(value_);
  }
  const Json& at(const std::string& key) const {
    const auto& object = as_object();
    const auto found = object.find(key);
    if (found == object.end()) throw Error("JSON object has no field: " + key);
    return found->second;
  }

 private:
  Value value_;
};

class JsonParser {
 public:
  explicit JsonParser(std::string text) : text_(std::move(text)) {}

  Json parse() {
    skip_space();
    Json result = parse_value();
    skip_space();
    if (position_ != text_.size()) fail("trailing content");
    return result;
  }

 private:
  [[noreturn]] void fail(const std::string& message) const {
    throw Error("invalid JSON at byte " + std::to_string(position_) +
                ": " + message);
  }

  void skip_space() {
    while (position_ < text_.size() &&
           std::isspace(static_cast<unsigned char>(text_[position_]))) {
      ++position_;
    }
  }

  bool consume(char expected) {
    if (position_ < text_.size() && text_[position_] == expected) {
      ++position_;
      return true;
    }
    return false;
  }

  bool literal(const char* value) {
    const std::size_t length = std::strlen(value);
    if (text_.compare(position_, length, value) != 0) return false;
    position_ += length;
    return true;
  }

  Json parse_value() {
    if (position_ >= text_.size()) fail("unexpected end of input");
    const char ch = text_[position_];
    if (ch == '{') return parse_object();
    if (ch == '[') return parse_array();
    if (ch == '"') return Json(parse_string());
    if (ch == 't' && literal("true")) return Json(true);
    if (ch == 'f' && literal("false")) return Json(false);
    if (ch == 'n' && literal("null")) return Json(nullptr);
    if (ch == '-' || (ch >= '0' && ch <= '9')) return parse_number();
    fail("unexpected token");
  }

  Json parse_object() {
    consume('{');
    Json::Object result;
    skip_space();
    if (consume('}')) return Json(std::move(result));
    while (true) {
      skip_space();
      if (position_ >= text_.size() || text_[position_] != '"') {
        fail("object key must be a string");
      }
      std::string key = parse_string();
      skip_space();
      if (!consume(':')) fail("expected ':'");
      skip_space();
      if (!result.emplace(std::move(key), parse_value()).second) {
        fail("duplicate object key");
      }
      skip_space();
      if (consume('}')) break;
      if (!consume(',')) fail("expected ',' or '}'");
    }
    return Json(std::move(result));
  }

  Json parse_array() {
    consume('[');
    Json::Array result;
    skip_space();
    if (consume(']')) return Json(std::move(result));
    while (true) {
      skip_space();
      result.push_back(parse_value());
      skip_space();
      if (consume(']')) break;
      if (!consume(',')) fail("expected ',' or ']'");
    }
    return Json(std::move(result));
  }

  static void append_utf8(std::string& output, std::uint32_t codepoint) {
    if (codepoint <= 0x7f) {
      output.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7ff) {
      output.push_back(static_cast<char>(0xc0 | (codepoint >> 6)));
      output.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
    } else if (codepoint <= 0xffff) {
      output.push_back(static_cast<char>(0xe0 | (codepoint >> 12)));
      output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
      output.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
    } else {
      output.push_back(static_cast<char>(0xf0 | (codepoint >> 18)));
      output.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3f)));
      output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
      output.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
    }
  }

  std::uint32_t parse_hex4() {
    if (position_ + 4 > text_.size()) fail("short Unicode escape");
    std::uint32_t value = 0;
    for (int index = 0; index < 4; ++index) {
      const char ch = text_[position_++];
      value <<= 4;
      if (ch >= '0' && ch <= '9') value |= static_cast<unsigned>(ch - '0');
      else if (ch >= 'a' && ch <= 'f') value |= static_cast<unsigned>(ch - 'a' + 10);
      else if (ch >= 'A' && ch <= 'F') value |= static_cast<unsigned>(ch - 'A' + 10);
      else fail("invalid Unicode escape");
    }
    return value;
  }

  std::string parse_string() {
    if (!consume('"')) fail("expected string");
    std::string result;
    while (position_ < text_.size()) {
      const unsigned char ch = static_cast<unsigned char>(text_[position_++]);
      if (ch == '"') return result;
      if (ch < 0x20) fail("control character in string");
      if (ch != '\\') {
        result.push_back(static_cast<char>(ch));
        continue;
      }
      if (position_ >= text_.size()) fail("short escape");
      const char escaped = text_[position_++];
      switch (escaped) {
        case '"': result.push_back('"'); break;
        case '\\': result.push_back('\\'); break;
        case '/': result.push_back('/'); break;
        case 'b': result.push_back('\b'); break;
        case 'f': result.push_back('\f'); break;
        case 'n': result.push_back('\n'); break;
        case 'r': result.push_back('\r'); break;
        case 't': result.push_back('\t'); break;
        case 'u': {
          std::uint32_t codepoint = parse_hex4();
          if (codepoint >= 0xd800 && codepoint <= 0xdbff) {
            if (position_ + 2 > text_.size() || text_[position_] != '\\' ||
                text_[position_ + 1] != 'u') {
              fail("unpaired high surrogate");
            }
            position_ += 2;
            const std::uint32_t low = parse_hex4();
            if (low < 0xdc00 || low > 0xdfff) fail("invalid low surrogate");
            codepoint =
                0x10000 + ((codepoint - 0xd800) << 10) + (low - 0xdc00);
          }
          append_utf8(result, codepoint);
          break;
        }
        default: fail("unknown escape");
      }
    }
    fail("unterminated string");
  }

  Json parse_number() {
    const std::size_t start = position_;
    consume('-');
    if (consume('0')) {
      if (position_ < text_.size() &&
          std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        fail("leading zero in number");
      }
    } else {
      if (position_ >= text_.size() || text_[position_] < '1' ||
          text_[position_] > '9') {
        fail("invalid number");
      }
      while (position_ < text_.size() &&
             std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        ++position_;
      }
    }
    bool floating = false;
    if (consume('.')) {
      floating = true;
      if (position_ >= text_.size() ||
          !std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        fail("invalid fractional number");
      }
      while (position_ < text_.size() &&
             std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        ++position_;
      }
    }
    if (position_ < text_.size() &&
        (text_[position_] == 'e' || text_[position_] == 'E')) {
      floating = true;
      ++position_;
      if (position_ < text_.size() &&
          (text_[position_] == '+' || text_[position_] == '-')) {
        ++position_;
      }
      if (position_ >= text_.size() ||
          !std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        fail("invalid exponent");
      }
      while (position_ < text_.size() &&
             std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        ++position_;
      }
    }
    const std::string token = text_.substr(start, position_ - start);
    try {
      if (floating) return Json(std::stod(token));
      return Json(static_cast<std::int64_t>(std::stoll(token)));
    } catch (const std::exception&) {
      fail("number out of range");
    }
  }

  std::string text_;
  std::size_t position_ = 0;
};

class Sha256 {
 public:
  Sha256() {
    state_ = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
              0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  }

  void update(const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    bit_length_ += static_cast<std::uint64_t>(size) * 8;
    while (size > 0) {
      const std::size_t take = std::min(size, block_.size() - block_size_);
      std::memcpy(block_.data() + block_size_, bytes, take);
      block_size_ += take;
      bytes += take;
      size -= take;
      if (block_size_ == block_.size()) {
        transform(block_.data());
        block_size_ = 0;
      }
    }
  }

  void update(const std::string& value) {
    update(value.data(), value.size());
  }

  std::array<std::uint8_t, 32> digest() const {
    Sha256 copy = *this;
    return copy.finish();
  }

  std::string hex_digest() const {
    const auto bytes = digest();
    static constexpr char kHex[] = "0123456789abcdef";
    std::string result(64, '0');
    for (std::size_t index = 0; index < bytes.size(); ++index) {
      result[index * 2] = kHex[bytes[index] >> 4];
      result[index * 2 + 1] = kHex[bytes[index] & 15];
    }
    return result;
  }

 private:
  static constexpr std::array<std::uint32_t, 64> kRound = {
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

  static std::uint32_t rotate_right(std::uint32_t value, int count) {
    return (value >> count) | (value << (32 - count));
  }

  void transform(const std::uint8_t* block) {
    std::array<std::uint32_t, 64> words{};
    for (int index = 0; index < 16; ++index) {
      words[index] =
          (static_cast<std::uint32_t>(block[index * 4]) << 24) |
          (static_cast<std::uint32_t>(block[index * 4 + 1]) << 16) |
          (static_cast<std::uint32_t>(block[index * 4 + 2]) << 8) |
          static_cast<std::uint32_t>(block[index * 4 + 3]);
    }
    for (int index = 16; index < 64; ++index) {
      const std::uint32_t s0 =
          rotate_right(words[index - 15], 7) ^
          rotate_right(words[index - 15], 18) ^
          (words[index - 15] >> 3);
      const std::uint32_t s1 =
          rotate_right(words[index - 2], 17) ^
          rotate_right(words[index - 2], 19) ^
          (words[index - 2] >> 10);
      words[index] =
          words[index - 16] + s0 + words[index - 7] + s1;
    }
    std::uint32_t a=state_[0], b=state_[1], c=state_[2], d=state_[3];
    std::uint32_t e=state_[4], f=state_[5], g=state_[6], h=state_[7];
    for (int index = 0; index < 64; ++index) {
      const std::uint32_t s1 =
          rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
      const std::uint32_t choice = (e & f) ^ ((~e) & g);
      const std::uint32_t temp1 =
          h + s1 + choice + kRound[index] + words[index];
      const std::uint32_t s0 =
          rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
      const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t temp2 = s0 + majority;
      h=g; g=f; f=e; e=d+temp1; d=c; c=b; b=a; a=temp1+temp2;
    }
    state_[0]+=a; state_[1]+=b; state_[2]+=c; state_[3]+=d;
    state_[4]+=e; state_[5]+=f; state_[6]+=g; state_[7]+=h;
  }

  std::array<std::uint8_t, 32> finish() {
    const std::uint64_t original_bits = bit_length_;
    block_[block_size_++] = 0x80;
    if (block_size_ > 56) {
      while (block_size_ < 64) block_[block_size_++] = 0;
      transform(block_.data());
      block_size_ = 0;
    }
    while (block_size_ < 56) block_[block_size_++] = 0;
    for (int shift = 56; shift >= 0; shift -= 8) {
      block_[block_size_++] =
          static_cast<std::uint8_t>(original_bits >> shift);
    }
    transform(block_.data());
    std::array<std::uint8_t, 32> result{};
    for (std::size_t index = 0; index < state_.size(); ++index) {
      result[index * 4] =
          static_cast<std::uint8_t>(state_[index] >> 24);
      result[index * 4 + 1] =
          static_cast<std::uint8_t>(state_[index] >> 16);
      result[index * 4 + 2] =
          static_cast<std::uint8_t>(state_[index] >> 8);
      result[index * 4 + 3] =
          static_cast<std::uint8_t>(state_[index]);
    }
    return result;
  }

  std::array<std::uint32_t, 8> state_{};
  std::array<std::uint8_t, 64> block_{};
  std::size_t block_size_ = 0;
  std::uint64_t bit_length_ = 0;
};

std::string sha256_text(const std::string& value) {
  Sha256 hash;
  hash.update(value);
  return hash.hex_digest();
}

std::string read_file(const fs::path& path) {
  std::ifstream source(path, std::ios::binary);
  if (!source) throw Error("cannot open file: " + path.string());
  std::ostringstream buffer;
  buffer << source.rdbuf();
  if (!source.good() && !source.eof()) {
    throw Error("cannot read file: " + path.string());
  }
  return buffer.str();
}

std::string json_escape(const std::string& value) {
  static constexpr char kHex[] = "0123456789abcdef";
  std::string result;
  result.reserve(value.size());
  for (unsigned char ch : value) {
    switch (ch) {
      case '"': result += "\\\""; break;
      case '\\': result += "\\\\"; break;
      case '\b': result += "\\b"; break;
      case '\f': result += "\\f"; break;
      case '\n': result += "\\n"; break;
      case '\r': result += "\\r"; break;
      case '\t': result += "\\t"; break;
      default:
        if (ch < 0x20) {
          result += "\\u00";
          result.push_back(kHex[ch >> 4]);
          result.push_back(kHex[ch & 15]);
        } else {
          result.push_back(static_cast<char>(ch));
        }
    }
  }
  return result;
}

std::string duration_text(double seconds) {
  if (!std::isfinite(seconds) || seconds < 0.0) return "--:--:--";
  const auto whole = static_cast<std::uint64_t>(seconds);
  const auto hours = whole / 3600;
  const auto minutes = (whole % 3600) / 60;
  const auto remainder = whole % 60;
  std::ostringstream out;
  out << std::setfill('0') << std::setw(2) << hours << ':'
      << std::setw(2) << minutes << ':' << std::setw(2) << remainder;
  return out.str();
}

struct Board {
  std::uint64_t black = 0;
  std::uint64_t white = 0;
};

std::uint64_t legal_moves(std::uint64_t player, std::uint64_t opponent) {
  std::uint64_t masked = opponent & kHorizontalMask;
  std::uint64_t f1 = masked & (player << 1);
  std::uint64_t f7 = masked & (player << 7);
  std::uint64_t f9 = masked & (player << 9);
  std::uint64_t f8 = opponent & (player << 8);
  f1 |= masked & (f1 << 1);
  f7 |= masked & (f7 << 7);
  f9 |= masked & (f9 << 9);
  f8 |= opponent & (f8 << 8);
  std::uint64_t p1 = masked & (masked << 1);
  std::uint64_t p7 = masked & (masked << 7);
  std::uint64_t p9 = masked & (masked << 9);
  std::uint64_t p8 = opponent & (opponent << 8);
  for (int i = 0; i < 2; ++i) {
    f1 |= p1 & (f1 << 2);
    f7 |= p7 & (f7 << 14);
    f9 |= p9 & (f9 << 18);
    f8 |= p8 & (f8 << 16);
  }
  std::uint64_t moves = (f1 << 1) | (f7 << 7) | (f9 << 9) | (f8 << 8);
  f1 = masked & (player >> 1);
  f7 = masked & (player >> 7);
  f9 = masked & (player >> 9);
  f8 = opponent & (player >> 8);
  f1 |= masked & (f1 >> 1);
  f7 |= masked & (f7 >> 7);
  f9 |= masked & (f9 >> 9);
  f8 |= opponent & (f8 >> 8);
  p1 >>= 1;
  p7 >>= 7;
  p9 >>= 9;
  p8 >>= 8;
  for (int i = 0; i < 2; ++i) {
    f1 |= p1 & (f1 >> 2);
    f7 |= p7 & (f7 >> 14);
    f9 |= p9 & (f9 >> 18);
    f8 |= p8 & (f8 >> 16);
  }
  moves |= (f1 >> 1) | (f7 >> 7) | (f9 >> 9) | (f8 >> 8);
  return moves & ~(player | opponent);
}

std::uint64_t ray_left(
    std::uint64_t move, std::uint64_t player, std::uint64_t opponent,
    int shift, std::uint64_t mask) {
  const std::uint64_t masked = opponent & mask;
  std::uint64_t cursor = masked & (move << shift);
  std::uint64_t captured = 0;
  while (cursor != 0) {
    captured |= cursor;
    const std::uint64_t next = cursor << shift;
    if ((next & player) != 0) return captured;
    cursor = masked & next;
  }
  return 0;
}

std::uint64_t ray_right(
    std::uint64_t move, std::uint64_t player, std::uint64_t opponent,
    int shift, std::uint64_t mask) {
  const std::uint64_t masked = opponent & mask;
  std::uint64_t cursor = masked & (move >> shift);
  std::uint64_t captured = 0;
  while (cursor != 0) {
    captured |= cursor;
    const std::uint64_t next = cursor >> shift;
    if ((next & player) != 0) return captured;
    cursor = masked & next;
  }
  return 0;
}

std::uint64_t flips_for(
    std::uint64_t move, std::uint64_t player, std::uint64_t opponent) {
  return ray_left(move, player, opponent, 1, kHorizontalMask) |
         ray_right(move, player, opponent, 1, kHorizontalMask) |
         ray_left(move, player, opponent, 7, kHorizontalMask) |
         ray_right(move, player, opponent, 7, kHorizontalMask) |
         ray_left(move, player, opponent, 9, kHorizontalMask) |
         ray_right(move, player, opponent, 9, kHorizontalMask) |
         ray_left(move, player, opponent, 8, kFull) |
         ray_right(move, player, opponent, 8, kFull);
}

Board initial_board() {
  Board board;
  board.white |= 1ULL << (3 + 3 * 8);
  board.black |= 1ULL << (4 + 3 * 8);
  board.black |= 1ULL << (3 + 4 * 8);
  board.white |= 1ULL << (4 + 4 * 8);
  return board;
}

std::uint64_t own(const Board& board, bool black) {
  return black ? board.black : board.white;
}

std::uint64_t other(const Board& board, bool black) {
  return black ? board.white : board.black;
}

void apply(Board& board, int cell, bool black) {
  const std::uint64_t move = 1ULL << cell;
  std::uint64_t player = own(board, black);
  std::uint64_t opponent = other(board, black);
  const std::uint64_t flips = flips_for(move, player, opponent);
  if (flips == 0) throw Error("internal illegal move");
  player |= move | flips;
  opponent &= ~flips;
  if (black) {
    board.black = player;
    board.white = opponent;
  } else {
    board.white = player;
    board.black = opponent;
  }
}

std::string relative_board(const Board& board, bool black) {
  const std::uint64_t player = own(board, black);
  const std::uint64_t opponent = other(board, black);
  std::string result(64, '-');
  for (int cell = 0; cell < 64; ++cell) {
    const std::uint64_t bit = 1ULL << cell;
    if ((player & bit) != 0) result[static_cast<std::size_t>(cell)] = 'X';
    else if ((opponent & bit) != 0) result[static_cast<std::size_t>(cell)] = 'O';
  }
  return result;
}

std::string coordinate(int cell) {
  std::string result;
  result += static_cast<char>('a' + cell % 8);
  result += static_cast<char>('1' + cell / 8);
  return result;
}

std::vector<int> parse_transcript(
    std::string line, const fs::path& path, std::uint64_t line_number) {
  while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) line.pop_back();
  if (line.empty() || line.size() % 2 != 0) {
    throw Error(path.string() + ":" + std::to_string(line_number) +
                ": malformed transcript");
  }
  std::vector<int> result;
  result.reserve(line.size() / 2);
  for (std::size_t offset = 0; offset < line.size(); offset += 2) {
    const char file = line[offset];
    const char rank = line[offset + 1];
    if (file < 'a' || file > 'h' || rank < '1' || rank > '8') {
      throw Error(path.string() + ":" + std::to_string(line_number) +
                  ": coordinate outside a1..h8");
    }
    result.push_back((rank - '1') * 8 + file - 'a');
  }
  return result;
}

struct Example {
  std::string board;
  int move = -1;
};

std::optional<Example> replay(
    const std::vector<int>& transcript, int random_plies,
    const fs::path& path, std::uint64_t line_number) {
  if (transcript.size() < static_cast<std::size_t>(random_plies)) {
    throw Error(path.string() + ":" + std::to_string(line_number) +
                ": transcript shorter than random prefix");
  }
  Board board = initial_board();
  bool black = true;
  for (std::size_t index = 0; index < transcript.size(); ++index) {
    const int cell = transcript[index];
    std::uint64_t legal = legal_moves(own(board, black), other(board, black));
    if (legal == 0) {
      const std::uint64_t passed =
          legal_moves(own(board, !black), other(board, !black));
      if (passed == 0) throw Error("transcript continues after game end");
      black = !black;
      legal = passed;
    }
    if ((legal & (1ULL << cell)) == 0) {
      throw Error(path.string() + ":" + std::to_string(line_number) +
                  ": illegal transcript move " + coordinate(cell));
    }
    apply(board, cell, black);
    black = !black;
    if (index + 1 == static_cast<std::size_t>(random_plies)) {
      std::uint64_t next = legal_moves(own(board, black), other(board, black));
      if (next == 0) {
        const std::uint64_t passed =
            legal_moves(own(board, !black), other(board, !black));
        if (passed == 0) return std::nullopt;
        black = !black;
        next = passed;
      }
      // A forced move has zero listwise CE and zero policy gradient.
      if ((next & (next - 1)) == 0) return std::nullopt;
      if (transcript.size() <= index + 1) {
        throw Error("non-terminal transcript has no policy target");
      }
      const int teacher = transcript[index + 1];
      if ((next & (1ULL << teacher)) == 0) {
        throw Error("policy target is not legal at random-prefix boundary");
      }
      // The existing v2 value-conversion manifest already proves complete
      // transcript legality and termination. Policy conversion only needs to
      // replay the random prefix and validate its immediate level-11 teacher.
      return Example{relative_board(board, black), teacher};
    }
  }
  return std::nullopt;
}

std::string rotate90(const std::string& board) {
  std::string result(64, '-');
  for (int y = 0; y < 8; ++y) {
    for (int x = 0; x < 8; ++x) {
      result[static_cast<std::size_t>(y * 8 + x)] =
          board[static_cast<std::size_t>((7 - x) * 8 + y)];
    }
  }
  return result;
}

std::string mirror(const std::string& board) {
  std::string result(64, '-');
  for (int y = 0; y < 8; ++y) {
    for (int x = 0; x < 8; ++x) {
      result[static_cast<std::size_t>(y * 8 + x)] =
          board[static_cast<std::size_t>(y * 8 + 7 - x)];
    }
  }
  return result;
}

std::string canonical_d4(const std::string& board) {
  std::string best = board;
  std::string rotated = board;
  for (int i = 0; i < 4; ++i) {
    best = std::min(best, rotated);
    best = std::min(best, mirror(rotated));
    rotated = rotate90(rotated);
  }
  return best;
}

std::uint64_t fnv1a(const std::string& value) {
  std::uint64_t hash = 14695981039346656037ULL;
  for (unsigned char ch : value) {
    hash ^= ch;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool selected(const std::string& board, const std::string& seed, int denominator) {
  return fnv1a("sample|" + seed + "|" + canonical_d4(board)) %
             static_cast<std::uint64_t>(denominator) == 0;
}

bool digest_less_than_ratio(
    const std::array<std::uint8_t, 32>& digest,
    std::uint64_t numerator, std::uint64_t denominator) {
  if (numerator == 0) return false;
  if (numerator >= denominator) return true;
  std::array<std::uint8_t, 32> threshold{};
  std::uint64_t remainder = numerator;
  for (int bit = 0; bit < 256; ++bit) {
    remainder *= 2;
    if (remainder >= denominator) {
      remainder -= denominator;
      threshold[static_cast<std::size_t>(bit / 8)] |=
          static_cast<std::uint8_t>(1U << (7 - bit % 8));
    }
  }
  return std::lexicographical_compare(
      digest.begin(), digest.end(), threshold.begin(), threshold.end());
}

int split_for(const std::string& board, const std::string& seed) {
  std::string material = kSplitMaterialPrefix;
  material.push_back('\0');
  material += seed;
  material.push_back('\0');
  material += canonical_d4(board);
  Sha256 hash;
  hash.update(material);
  const auto digest = hash.digest();
  if (digest_less_than_ratio(digest, 9, 10)) return 0;
  if (digest_less_than_ratio(digest, 19, 20)) return 1;
  return 2;
}

int phase_for(int random_plies) {
  return std::max(0, std::min(3, random_plies / 10 - 2));
}

bool decimal(const std::string& value) {
  return !value.empty() && std::all_of(
      value.begin(), value.end(),
      [](unsigned char ch) { return std::isdigit(ch) != 0; });
}

struct Source {
  fs::path path;
  int random_plies = 0;
  int part = 0;
  std::string relative_path;
  std::uint64_t expected_size_bytes = 0;
  std::uint64_t expected_lines = 0;
  std::string expected_sha256;
};

struct SourceFingerprint {
  int random_plies = 0;
  std::uint64_t size_bytes = 0;
  std::uint64_t lines = 0;
  std::string sha256;
};

struct UpstreamContract {
  std::unordered_map<std::string, SourceFingerprint> sources;
  std::string manifest_sha256;
};

std::string normalized_relative_path(std::string value) {
  std::replace(value.begin(), value.end(), '\\', '/');
  while (value.rfind("./", 0) == 0) value.erase(0, 2);
  return value;
}

std::string source_key(int part, const std::string& relative_path) {
  return std::to_string(part) + "|" + normalized_relative_path(relative_path);
}

bool valid_sha256(const std::string& value) {
  return value.size() == 64 && std::all_of(
      value.begin(), value.end(), [](unsigned char ch) {
        return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
      });
}

std::uint64_t nonnegative_integer(
    const Json& value, const std::string& field) {
  const std::int64_t number = value.as_int();
  if (number < 0) throw Error("upstream manifest has negative " + field);
  return static_cast<std::uint64_t>(number);
}

UpstreamContract load_upstream_manifest(const fs::path& path) {
  const std::string text = read_file(path);
  const Json manifest = JsonParser(text).parse();
  if (manifest.at("schema_version").as_int() != 2 ||
      manifest.at("status").as_string() != "verified-full") {
    throw Error("upstream manifest is not schema-2 verified-full: " +
                path.string());
  }
  const Json& counts = manifest.at("counts");
  if (counts.at("source_files").as_int() != 5200 ||
      counts.at("source_games").as_int() != 52000000) {
    throw Error("upstream manifest does not describe the full v0002 dataset");
  }
  const Json& split = manifest.at("split");
  if (split.at("algorithm").as_string() != kSplitAlgorithm ||
      split.at("unit").as_string() != kSplitUnit ||
      split.at("seed").as_string() != "20260715") {
    throw Error("upstream manifest split contract is incompatible");
  }
  const Json& ratios = split.at("ratios");
  if (ratios.at("train").as_string() != "0.9" ||
      ratios.at("val").as_string() != "0.05" ||
      ratios.at("test").as_string() != "0.05") {
    throw Error("upstream manifest split ratios are incompatible");
  }

  UpstreamContract contract;
  contract.manifest_sha256 = sha256_text(text);
  const auto& sources = manifest.at("sources").as_array();
  if (sources.size() != 5200) {
    throw Error("upstream manifest must contain exactly 5200 source receipts");
  }
  contract.sources.reserve(sources.size());
  std::uint64_t total_lines = 0;
  for (const Json& item : sources) {
    if (item.at("schema_version").as_int() != 2 ||
        item.at("status").as_string() != "complete") {
      throw Error("upstream manifest contains an incomplete source receipt");
    }
    const int part = static_cast<int>(item.at("part").as_int());
    if (part < 0 || part > 1) {
      throw Error("upstream manifest source part is outside 0..1");
    }
    const int random_plies =
        static_cast<int>(item.at("random_plies").as_int());
    if (random_plies < 8 || random_plies > 59) {
      throw Error("upstream manifest random_plies is outside 8..59");
    }
    const std::string relative_path =
        normalized_relative_path(item.at("relative_path").as_string());
    if (relative_path.empty() || relative_path.front() == '/' ||
        relative_path.find("../") != std::string::npos) {
      throw Error("upstream manifest contains an unsafe relative path");
    }
    const std::string expected_id =
        "part" + std::to_string(part) + "/" + relative_path;
    if (item.at("source_id").as_string() != expected_id) {
      throw Error("upstream manifest source_id/relative_path mismatch");
    }
    const Json& fingerprint = item.at("fingerprint");
    SourceFingerprint expected;
    expected.random_plies = random_plies;
    expected.size_bytes =
        nonnegative_integer(fingerprint.at("size_bytes"), "size_bytes");
    expected.lines =
        nonnegative_integer(fingerprint.at("transcript_lines"),
                            "transcript_lines");
    expected.sha256 = fingerprint.at("sha256").as_string();
    const std::uint64_t source_lines =
        nonnegative_integer(item.at("source_transcript_lines"),
                            "source_transcript_lines");
    if (expected.lines != 10000 || expected.size_bytes == 0 ||
        expected.lines != source_lines || !valid_sha256(expected.sha256)) {
      throw Error("upstream manifest contains an invalid source fingerprint");
    }
    total_lines += expected.lines;
    if (!contract.sources.emplace(
            source_key(part, relative_path), std::move(expected)).second) {
      throw Error("upstream manifest contains a duplicate source path");
    }
  }
  if (total_lines != 52000000) {
    throw Error("upstream manifest source fingerprints do not total 52000000 lines");
  }
  return contract;
}

std::vector<Source> discover(
    const std::array<fs::path, 2>& roots,
    const UpstreamContract& upstream) {
  std::vector<Source> result;
  std::unordered_map<std::string, bool> seen;
  seen.reserve(upstream.sources.size());
  for (int part = 0; part < 2; ++part) {
    const fs::path root = fs::absolute(roots[part]).lexically_normal();
    if (!fs::is_directory(root)) throw Error("input root missing: " + root.string());
    for (const auto& entry : fs::recursive_directory_iterator(root)) {
      if (!entry.is_regular_file() || entry.path().extension() != ".txt") continue;
      const std::string parent = entry.path().parent_path().filename().string();
      const std::string stem = entry.path().stem().string();
      if (!decimal(parent) || !decimal(stem)) continue;
      const int random_plies = std::stoi(parent);
      if (random_plies < 8 || random_plies > 59) continue;
      const fs::path within_root = entry.path().lexically_relative(root);
      const std::string relative_path =
          normalized_relative_path(within_root.generic_string());
      const std::string key = source_key(part, relative_path);
      const auto expected = upstream.sources.find(key);
      if (expected == upstream.sources.end()) {
        throw Error("raw source is absent from upstream manifest: " +
                    entry.path().string());
      }
      if (expected->second.random_plies != random_plies) {
        throw Error("raw source random_plies disagrees with upstream manifest: " +
                    entry.path().string());
      }
      if (!seen.emplace(key, true).second) {
        throw Error("raw source discovered more than once: " +
                    entry.path().string());
      }
      result.push_back(Source{
          entry.path(), random_plies, part, relative_path,
          expected->second.size_bytes, expected->second.lines,
          expected->second.sha256});
    }
  }
  if (seen.size() != upstream.sources.size()) {
    throw Error(
        "raw source roots do not match the upstream manifest 1:1 (found " +
        std::to_string(seen.size()) + " of " +
        std::to_string(upstream.sources.size()) + ")");
  }
  std::sort(result.begin(), result.end(), [](const Source& left, const Source& right) {
    if (left.random_plies != right.random_plies) {
      return left.random_plies < right.random_plies;
    }
    if (left.part != right.part) return left.part < right.part;
    return left.relative_path < right.relative_path;
  });
  std::unordered_map<std::string, bool> output_keys;
  output_keys.reserve(result.size());
  for (const Source& source : result) {
    const std::string key =
        std::to_string(source.random_plies) + "/" +
        source.path.filename().generic_string();
    if (!output_keys.emplace(key, true).second) {
      throw Error("two raw sources map to the same output shard: " + key);
    }
  }
  return result;
}

struct Counts {
  std::uint64_t games = 0;
  std::uint64_t source_fingerprints_verified = 0;
  std::uint64_t eligible = 0;
  std::uint64_t skipped_no_choice = 0;
  std::uint64_t selected = 0;
  std::array<std::uint64_t, 3> split{};
  std::array<std::array<std::uint64_t, 4>, 3> split_phase{};
};

Counts convert_source(
    const Source& source, const fs::path& output_root,
    const std::string& sample_seed, const std::string& split_seed,
    int denominator, int expected_games) {
  std::array<fs::path, 3> output;
  std::array<fs::path, 3> temporary;
  std::array<std::ofstream, 3> writers;
  for (int split = 0; split < 3; ++split) {
    output[split] = output_root / kSplitNames[split] /
                    std::to_string(source.random_plies) /
                    source.path.filename();
    temporary[split] = output[split];
    temporary[split] += ".part";
    fs::create_directories(output[split].parent_path());
    if (fs::exists(output[split])) {
      throw Error("output already exists; use a new output root: " + output[split].string());
    }
    writers[split].open(temporary[split], std::ios::binary | std::ios::trunc);
    if (!writers[split]) throw Error("cannot create " + temporary[split].string());
  }

  Counts counts;
  std::ifstream input(source.path, std::ios::binary);
  if (!input) throw Error("cannot open " + source.path.string());
  Sha256 source_hash;
  std::uint64_t source_bytes = 0;
  std::string line;
  std::uint64_t line_number = 0;
  while (std::getline(input, line)) {
    source_hash.update(line);
    source_bytes += static_cast<std::uint64_t>(line.size());
    if (!input.eof()) {
      static constexpr char kNewline = '\n';
      source_hash.update(&kNewline, 1);
      ++source_bytes;
    }
    ++line_number;
    const auto transcript = parse_transcript(line, source.path, line_number);
    const auto example = replay(transcript, source.random_plies, source.path, line_number);
    ++counts.games;
    if (!example) {
      ++counts.skipped_no_choice;
      continue;
    }
    ++counts.eligible;
    if (!selected(example->board, sample_seed, denominator)) continue;
    const int split = split_for(example->board, split_seed);
    writers[split] << example->board << ' ' << coordinate(example->move) << '\n';
    if (!writers[split]) throw Error("cannot write policy shard");
    ++counts.selected;
    ++counts.split[split];
    ++counts.split_phase[split][phase_for(source.random_plies)];
  }
  if (!input.eof()) throw Error("read failure: " + source.path.string());
  if (counts.games != source.expected_lines ||
      source_bytes != source.expected_size_bytes ||
      source_hash.hex_digest() != source.expected_sha256) {
    throw Error(
        "raw source fingerprint differs from upstream manifest: " +
        source.path.string());
  }
  if (expected_games > 0 &&
      counts.games != static_cast<std::uint64_t>(expected_games)) {
    throw Error("source line count mismatch: " + source.path.string());
  }
  counts.source_fingerprints_verified = 1;
  for (int split = 0; split < 3; ++split) {
    writers[split].close();
    if (!writers[split]) {
      throw Error("cannot finalize policy shard: " + temporary[split].string());
    }
    fs::rename(temporary[split], output[split]);
  }
  return counts;
}

struct Options {
  std::array<fs::path, 2> roots = {
      fs::path("C:/Code/OthelloAI_05_training/resources/Egaroucid_Train_Data_v0002_0"),
      fs::path("C:/Code/OthelloAI_05_training/resources/Egaroucid_Train_Data_v0002_1")};
  fs::path output = "data/processed/egaroucid_policy_v1";
  fs::path verified_manifest =
      "C:/Code/OthelloAI_05_training/data/processed/egaroucid_v2/"
      "conversion_manifest.json";
  std::string sample_seed = "20260720";
  std::string split_seed = "20260715";
  int denominator = 16;
  int workers = 12;
  int expected_games = 10000;
  int limit_files = 0;
  bool quiet = false;
  bool self_test = false;
};

Options parse_options(int argc, char** argv) {
  Options options;
  auto value = [&](int& index, const std::string& name) {
    if (++index >= argc) throw Error("missing value for " + name);
    return std::string(argv[index]);
  };
  for (int index = 1; index < argc; ++index) {
    const std::string arg = argv[index];
    if (arg == "--root0") options.roots[0] = value(index, arg);
    else if (arg == "--root1") options.roots[1] = value(index, arg);
    else if (arg == "--output-root") options.output = value(index, arg);
    else if (arg == "--verified-manifest") options.verified_manifest = value(index, arg);
    else if (arg == "--sample-seed") options.sample_seed = value(index, arg);
    else if (arg == "--split-seed") options.split_seed = value(index, arg);
    else if (arg == "--sample-denominator") options.denominator = std::stoi(value(index, arg));
    else if (arg == "--workers") options.workers = std::stoi(value(index, arg));
    else if (arg == "--expected-games-per-file") options.expected_games = std::stoi(value(index, arg));
    else if (arg == "--limit-files") options.limit_files = std::stoi(value(index, arg));
    else if (arg == "--quiet") options.quiet = true;
    else if (arg == "--self-test") options.self_test = true;
    else if (arg == "--help" || arg == "-h") {
      std::cout
          << "egaroucid_policy_converter [options]\n"
          << "  --root0 PATH --root1 PATH\n"
          << "  --output-root PATH\n"
          << "  --verified-manifest PATH  verified value-converter manifest\n"
          << "  --sample-denominator N  default 16\n"
          << "  --sample-seed TEXT       default 20260720\n"
          << "  --split-seed TEXT        default 20260715\n"
          << "  --workers N              default 12\n"
          << "  --limit-files N          smoke conversion\n"
          << "  --self-test\n";
      std::exit(0);
    } else {
      throw Error("unknown option: " + arg);
    }
  }
  if (options.denominator <= 0 || options.workers <= 0 ||
      options.expected_games < 0 || options.limit_files < 0) {
    throw Error(
        "sample denominator/workers must be positive and expected games "
        "and file limit must be zero or positive");
  }
  return options;
}

void self_test() {
  if (sha256_text("") !=
          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" ||
      sha256_text("abc") !=
          "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") {
    throw Error("self-test SHA-256 vectors failed");
  }
  const Json parsed = JsonParser(
      "{\"schema_version\":2,\"status\":\"verified-full\"}").parse();
  if (parsed.at("schema_version").as_int() != 2 ||
      parsed.at("status").as_string() != "verified-full") {
    throw Error("self-test JSON parser failed");
  }
  if (split_for(
          "---------------------------------------------------------------X",
          "20260715") != 0 ||
      split_for(
          "----------------------------------------------------------X--X-X",
          "20260715") != 1 ||
      split_for(
          "-----------------------------------------------------------X---X",
          "20260715") != 2) {
    throw Error("self-test original_05 SHA-256 split vectors failed");
  }
  const std::string full_game =
      "c4e3f2e2f4c5c6g4f5e6d3c3c2d6f1b5a6b4a5b6f3a3b3c1d2e1c7d1"
      "b1g3d7a4a2e7g2d8h3b8f8f6g7g6h5h8g5h4h7h6f7e8g8b2c8a7b7a1"
      "a8g1h2h1";
  const auto moves = parse_transcript(full_game, "self-test.txt", 1);
  const auto example = replay(moves, 8, "self-test.txt", 1);
  if (!example || example->board !=
          "------------OX------O-----XOOOO---XXO-----X---------------------" ||
      coordinate(example->move) != "f5") {
    throw Error("self-test replay/policy target failed");
  }
  const std::string canonical = canonical_d4(example->board);
  std::string rotated = example->board;
  for (int i = 0; i < 4; ++i) {
    if (canonical_d4(rotated) != canonical ||
        selected(rotated, "seed", 16) != selected(example->board, "seed", 16) ||
        split_for(rotated, "seed") != split_for(example->board, "seed")) {
      throw Error("self-test D4 hashing failed");
    }
    rotated = rotate90(rotated);
  }
  std::cout
      << "SELF-TEST PASS: sha256=yes json=yes split-original05=yes "
         "replay=yes policy=f5 d4-hash=yes schema="
      << kFeatureSchema << '\n';
}

void write_manifest(
    const Options& options, const std::vector<Source>& sources,
    const Counts& counts, const UpstreamContract& upstream, double elapsed) {
  const fs::path path = options.output / "conversion_manifest.json";
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw Error("cannot create manifest");
  const bool all_source_fingerprints_matched =
      options.limit_files == 0 && sources.size() == 5200 &&
      counts.games == 52000000 &&
      counts.source_fingerprints_verified == 5200;
  const bool verified_full =
      all_source_fingerprints_matched && options.expected_games == 10000 &&
      options.sample_seed == "20260720" && options.denominator == 16 &&
      options.split_seed == "20260715";
  out << "{\n"
      << "  \"schema_version\": 1,\n"
      << "  \"status\": \""
      << (verified_full ? "verified-full" : "limited")
      << "\",\n"
      << "  \"dataset_kind\": \"egaroucid_policy_teacher_v1\",\n"
      << "  \"feature_schema\": \"" << kFeatureSchema << "\",\n"
      << "  \"row_schema\": \"relative-board-64 teacher-move-a1h8 multi-legal-roots-only\",\n"
      << "  \"upstream_verification\": \"egaroucid-v2-manifest-verified-full\",\n"
      << "  \"upstream_manifest_sha256\": \""
      << upstream.manifest_sha256 << "\",\n"
      << "  \"source_paths_matched_upstream\": true,\n"
      << "  \"source_fingerprints_verified\": "
      << counts.source_fingerprints_verified << ",\n"
      << "  \"all_source_fingerprints_matched\": "
      << (all_source_fingerprints_matched ? "true" : "false") << ",\n"
      << "  \"sample\": {\"algorithm\": \"" << kSampleHashAlgorithm
      << "\", \"unit\": \"" << kSplitUnit
      << "\", \"seed\": \"" << json_escape(options.sample_seed)
      << "\", \"numerator\": 1, \"denominator\": " << options.denominator
      << "},\n"
      << "  \"split\": {\"algorithm\": \"" << kSplitAlgorithm
      << "\", \"seed\": \"" << json_escape(options.split_seed)
      << "\", \"ratios\": {\"train\": 0.9, \"val\": 0.05, \"test\": 0.05}, "
      << "\"unit\": \"" << kSplitUnit << "\"},\n"
      << "  \"source_files\": " << sources.size() << ",\n"
      << "  \"source_games\": " << counts.games << ",\n"
      << "  \"eligible_multi_legal_roots\": " << counts.eligible << ",\n"
      << "  \"skipped_no_choice\": " << counts.skipped_no_choice << ",\n"
      << "  \"selected_records\": " << counts.selected << ",\n"
      << "  \"by_split\": {\"train\": " << counts.split[0]
      << ", \"val\": " << counts.split[1] << ", \"test\": " << counts.split[2] << "},\n"
      << "  \"by_split_and_phase\": {\n";
  for (int split = 0; split < 3; ++split) {
    out << "    \"" << kSplitNames[split] << "\": {";
    for (int phase = 0; phase < 4; ++phase) {
      if (phase != 0) out << ", ";
      out << "\"" << phase << "\": " << counts.split_phase[split][phase];
    }
    out << "}" << (split == 2 ? "\n" : ",\n");
  }
  out << "  },\n"
      << "  \"elapsed_seconds\": " << std::fixed << std::setprecision(3) << elapsed << "\n"
      << "}\n";
  out.flush();
  if (!out) throw Error("cannot finalize conversion manifest");
}

int run(const Options& options) {
  if (fs::exists(options.output)) {
    throw Error("output root already exists; refusing to overwrite: " + options.output.string());
  }
  const UpstreamContract upstream =
      load_upstream_manifest(options.verified_manifest);
  std::vector<Source> sources = discover(options.roots, upstream);
  if (options.limit_files > 0 &&
      static_cast<std::size_t>(options.limit_files) < sources.size()) {
    sources.resize(static_cast<std::size_t>(options.limit_files));
  }
  if (sources.empty()) throw Error("no source files discovered");
  if (options.limit_files == 0 && sources.size() != 5200) {
    throw Error("full conversion requires exactly 5200 source files");
  }
  fs::create_directories(options.output);

  std::atomic<std::size_t> next{0};
  std::atomic<std::size_t> done{0};
  std::atomic<std::uint64_t> games{0};
  std::mutex mutex;
  Counts total;
  std::exception_ptr failure;
  std::atomic<bool> failed{false};
  const auto started = std::chrono::steady_clock::now();
  auto worker = [&]() {
    try {
      while (true) {
        const std::size_t index = next.fetch_add(1);
        if (index >= sources.size()) return;
        Counts local = convert_source(
            sources[index], options.output, options.sample_seed, options.split_seed,
            options.denominator, options.expected_games);
        {
          std::lock_guard<std::mutex> lock(mutex);
          total.games += local.games;
          total.source_fingerprints_verified +=
              local.source_fingerprints_verified;
          total.eligible += local.eligible;
          total.skipped_no_choice += local.skipped_no_choice;
          total.selected += local.selected;
          for (int split = 0; split < 3; ++split) {
            total.split[split] += local.split[split];
            for (int phase = 0; phase < 4; ++phase) {
              total.split_phase[split][phase] += local.split_phase[split][phase];
            }
          }
        }
        games.fetch_add(local.games);
        done.fetch_add(1);
      }
    } catch (...) {
      std::lock_guard<std::mutex> lock(mutex);
      if (!failure) failure = std::current_exception();
      failed.store(true, std::memory_order_release);
      next.store(sources.size());
    }
  };

  std::vector<std::thread> threads;
  for (int i = 0; i < std::min<int>(options.workers, static_cast<int>(sources.size())); ++i) {
    threads.emplace_back(worker);
  }
  while (done.load() < sources.size() &&
         !failed.load(std::memory_order_acquire)) {
    std::this_thread::sleep_for(std::chrono::seconds(1));
    if (!options.quiet) {
      const std::size_t completed = done.load();
      const std::uint64_t completed_games = games.load();
      const double elapsed = std::chrono::duration<double>(
          std::chrono::steady_clock::now() - started).count();
      const double rate = completed_games / std::max(0.001, elapsed);
      const double fraction =
          static_cast<double>(completed) / static_cast<double>(sources.size());
      constexpr int width = 24;
      const int filled = std::clamp(
          static_cast<int>(fraction * width), 0, width);
      const double eta = completed == 0
          ? std::numeric_limits<double>::infinity()
          : elapsed * (sources.size() - completed) / completed;
      std::cerr << "\r[policy convert] |"
                << std::string(filled, '#')
                << std::string(width - filled, '.') << "| "
                << completed << "/" << sources.size() << " files | "
                << completed_games << " games | "
                << std::fixed << std::setprecision(0) << rate << " games/s | "
                << duration_text(elapsed) << " elapsed | "
                << duration_text(eta) << " ETA"
                << std::flush;
    }
  }
  for (auto& thread : threads) thread.join();
  if (!options.quiet) std::cerr << '\n';
  if (failure) std::rethrow_exception(failure);
  if (total.eligible + total.skipped_no_choice != total.games) {
    throw Error("internal policy-root accounting mismatch");
  }
  const double elapsed = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - started).count();
  write_manifest(options, sources, total, upstream, elapsed);
  std::cout << "{\"event\":\"conversion_complete\",\"records\":"
            << total.selected << ",\"manifest\":\""
            << json_escape(
                   (options.output / "conversion_manifest.json").string())
            << "\"}\n";
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options options = parse_options(argc, argv);
    if (options.self_test) {
      self_test();
      return 0;
    }
    return run(options);
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    return 1;
  }
}
