// Egaroucid v0002 transcript -> evaluator-position converter.
//
// This is intentionally a single, dependency-free C++17 translation unit so
// the Windows training copy can be built with the installed MSYS2 g++.

#define NOMINMAX

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <variant>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

constexpr int kMinRandomPlies = 8;
constexpr int kMaxRandomPlies = 59;
constexpr int kExpectedFilesPerPly = 100;
constexpr std::int64_t kExpectedGamesPerFile = 10'000;
constexpr std::int64_t kExpectedGamesPerPly = 1'000'000;
constexpr std::int64_t kExpectedSourceFiles = 5'200;
constexpr std::int64_t kExpectedSourceGames = 52'000'000;
constexpr int kReceiptSchema = 2;
constexpr int kManifestSchema = 2;
constexpr const char* kSplitAlgorithm = "sha256-canonical-d4-board-v1";
constexpr const char* kSplitUnit = "canonical_d4_relative_board";
constexpr const char* kStableId =
    "lexicographically smallest D4 transform of the 64-cell relative board";
constexpr std::array<const char*, 3> kSplitNames = {"train", "val", "test"};

class ConversionError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

std::string path_text(const fs::path& path) {
#ifdef _WIN32
  const std::wstring wide = path.wstring();
  if (wide.empty()) return {};
  const int bytes = WideCharToMultiByte(CP_UTF8, 0, wide.data(),
                                        static_cast<int>(wide.size()), nullptr,
                                        0, nullptr, nullptr);
  if (bytes <= 0) throw ConversionError("could not encode Windows path as UTF-8");
  std::string result(static_cast<std::size_t>(bytes), '\0');
  WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()),
                      result.data(), bytes, nullptr, nullptr);
  return result;
#else
  return path.string();
#endif
}

std::string generic_path_text(const fs::path& path) {
  std::string result = path_text(path);
  std::replace(result.begin(), result.end(), '\\', '/');
  return result;
}

std::string ascii_lower(std::string value) {
  for (char& ch : value) {
    const unsigned char byte = static_cast<unsigned char>(ch);
    if (byte >= 'A' && byte <= 'Z') ch = static_cast<char>(byte - 'A' + 'a');
  }
  return value;
}

// ------------------------------ Minimal JSON ------------------------------

class Json {
 public:
  using Array = std::vector<Json>;
  using Object = std::map<std::string, Json>;
  using Value = std::variant<std::nullptr_t, bool, std::int64_t, double,
                             std::string, Array, Object>;

  Json() : value_(nullptr) {}
  Json(std::nullptr_t) : value_(nullptr) {}
  Json(bool value) : value_(value) {}
  Json(int value) : value_(static_cast<std::int64_t>(value)) {}
  Json(std::int64_t value) : value_(value) {}
  Json(double value) : value_(value) {}
  Json(const char* value) : value_(std::string(value)) {}
  Json(std::string value) : value_(std::move(value)) {}
  Json(Array value) : value_(std::move(value)) {}
  Json(Object value) : value_(std::move(value)) {}

  bool is_null() const { return std::holds_alternative<std::nullptr_t>(value_); }
  bool is_bool() const { return std::holds_alternative<bool>(value_); }
  bool is_int() const { return std::holds_alternative<std::int64_t>(value_); }
  bool is_double() const { return std::holds_alternative<double>(value_); }
  bool is_string() const { return std::holds_alternative<std::string>(value_); }
  bool is_array() const { return std::holds_alternative<Array>(value_); }
  bool is_object() const { return std::holds_alternative<Object>(value_); }

  bool as_bool() const {
    if (!is_bool()) throw ConversionError("JSON value is not a boolean");
    return std::get<bool>(value_);
  }
  std::int64_t as_int() const {
    if (!is_int()) throw ConversionError("JSON value is not an integer");
    return std::get<std::int64_t>(value_);
  }
  double as_double() const {
    if (is_double()) return std::get<double>(value_);
    if (is_int()) return static_cast<double>(std::get<std::int64_t>(value_));
    throw ConversionError("JSON value is not numeric");
  }
  const std::string& as_string() const {
    if (!is_string()) throw ConversionError("JSON value is not a string");
    return std::get<std::string>(value_);
  }
  const Array& as_array() const {
    if (!is_array()) throw ConversionError("JSON value is not an array");
    return std::get<Array>(value_);
  }
  Array& as_array() {
    if (!is_array()) throw ConversionError("JSON value is not an array");
    return std::get<Array>(value_);
  }
  const Object& as_object() const {
    if (!is_object()) throw ConversionError("JSON value is not an object");
    return std::get<Object>(value_);
  }
  Object& as_object() {
    if (!is_object()) throw ConversionError("JSON value is not an object");
    return std::get<Object>(value_);
  }

  const Json& at(const std::string& key) const {
    const auto& object = as_object();
    const auto found = object.find(key);
    if (found == object.end()) throw ConversionError("JSON object has no field: " + key);
    return found->second;
  }
  Json& operator[](const std::string& key) {
    if (!is_object()) value_ = Object{};
    return std::get<Object>(value_)[key];
  }

  bool operator==(const Json& other) const { return value_ == other.value_; }
  bool operator!=(const Json& other) const { return !(*this == other); }

 private:
  Value value_;
};

Json object(std::initializer_list<std::pair<const std::string, Json>> values) {
  Json::Object result;
  for (const auto& value : values) result.emplace(value.first, value.second);
  return Json(std::move(result));
}

Json array(std::initializer_list<Json> values) {
  return Json(Json::Array(values));
}

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
    throw ConversionError("invalid JSON at byte " + std::to_string(position_) +
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

  bool literal(const char* value) {
    const std::size_t length = std::strlen(value);
    if (text_.compare(position_, length, value) != 0) return false;
    position_ += length;
    return true;
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
            codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + (low - 0xdc00);
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
      if (position_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        fail("leading zero in number");
      }
    } else {
      if (position_ >= text_.size() || text_[position_] < '1' || text_[position_] > '9') {
        fail("invalid number");
      }
      while (position_ < text_.size() &&
             std::isdigit(static_cast<unsigned char>(text_[position_]))) ++position_;
    }
    bool floating = false;
    if (consume('.')) {
      floating = true;
      if (position_ >= text_.size() ||
          !std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        fail("invalid fractional number");
      }
      while (position_ < text_.size() &&
             std::isdigit(static_cast<unsigned char>(text_[position_]))) ++position_;
    }
    if (position_ < text_.size() && (text_[position_] == 'e' || text_[position_] == 'E')) {
      floating = true;
      ++position_;
      if (position_ < text_.size() && (text_[position_] == '+' || text_[position_] == '-')) {
        ++position_;
      }
      if (position_ >= text_.size() ||
          !std::isdigit(static_cast<unsigned char>(text_[position_]))) {
        fail("invalid exponent");
      }
      while (position_ < text_.size() &&
             std::isdigit(static_cast<unsigned char>(text_[position_]))) ++position_;
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

void write_json_string(std::ostream& output, const std::string& value) {
  output.put('"');
  static constexpr char kHex[] = "0123456789abcdef";
  for (const unsigned char ch : value) {
    switch (ch) {
      case '"': output << "\\\""; break;
      case '\\': output << "\\\\"; break;
      case '\b': output << "\\b"; break;
      case '\f': output << "\\f"; break;
      case '\n': output << "\\n"; break;
      case '\r': output << "\\r"; break;
      case '\t': output << "\\t"; break;
      default:
        if (ch < 0x20) {
          output << "\\u00" << kHex[ch >> 4] << kHex[ch & 15];
        } else {
          output.put(static_cast<char>(ch));
        }
    }
  }
  output.put('"');
}

void write_json(std::ostream& output, const Json& value, int indent = 0, int depth = 0) {
  const auto newline = [&](int extra = 0) {
    if (indent > 0) output << '\n' << std::string((depth + extra) * indent, ' ');
  };
  if (value.is_null()) output << "null";
  else if (value.is_bool()) output << (value.as_bool() ? "true" : "false");
  else if (value.is_int()) output << value.as_int();
  else if (value.is_double()) output << std::setprecision(17) << value.as_double();
  else if (value.is_string()) write_json_string(output, value.as_string());
  else if (value.is_array()) {
    output << '[';
    const auto& values = value.as_array();
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (index != 0) output << ',';
      newline(1);
      write_json(output, values[index], indent, depth + 1);
    }
    if (!values.empty()) newline();
    output << ']';
  } else {
    output << '{';
    const auto& values = value.as_object();
    std::size_t index = 0;
    for (const auto& [key, child] : values) {
      if (index++ != 0) output << ',';
      newline(1);
      write_json_string(output, key);
      output << (indent > 0 ? ": " : ":");
      write_json(output, child, indent, depth + 1);
    }
    if (!values.empty()) newline();
    output << '}';
  }
}

std::string json_text(const Json& value, int indent = 0) {
  std::ostringstream output;
  write_json(output, value, indent);
  return output.str();
}

Json read_json(const fs::path& path) {
  std::ifstream source(path, std::ios::binary);
  if (!source) throw ConversionError("cannot open JSON: " + path_text(path));
  std::ostringstream buffer;
  buffer << source.rdbuf();
  if (!source.good() && !source.eof()) {
    throw ConversionError("cannot read JSON: " + path_text(path));
  }
  try {
    return JsonParser(buffer.str()).parse();
  } catch (const ConversionError& error) {
    throw ConversionError("cannot parse " + path_text(path) + ": " + error.what());
  }
}

// ------------------------------- SHA-256 ----------------------------------

class Sha256 {
 public:
  Sha256() { reset(); }

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

  void update(const std::string& value) { update(value.data(), value.size()); }

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

  void reset() {
    state_ = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
              0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    block_.fill(0);
    block_size_ = 0;
    bit_length_ = 0;
  }

  void transform(const std::uint8_t* block) {
    std::array<std::uint32_t, 64> words{};
    for (int index = 0; index < 16; ++index) {
      words[index] = (static_cast<std::uint32_t>(block[index * 4]) << 24) |
                     (static_cast<std::uint32_t>(block[index * 4 + 1]) << 16) |
                     (static_cast<std::uint32_t>(block[index * 4 + 2]) << 8) |
                     static_cast<std::uint32_t>(block[index * 4 + 3]);
    }
    for (int index = 16; index < 64; ++index) {
      const std::uint32_t s0 = rotate_right(words[index - 15], 7) ^
                               rotate_right(words[index - 15], 18) ^
                               (words[index - 15] >> 3);
      const std::uint32_t s1 = rotate_right(words[index - 2], 17) ^
                               rotate_right(words[index - 2], 19) ^
                               (words[index - 2] >> 10);
      words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }
    std::uint32_t a=state_[0], b=state_[1], c=state_[2], d=state_[3];
    std::uint32_t e=state_[4], f=state_[5], g=state_[6], h=state_[7];
    for (int index = 0; index < 64; ++index) {
      const std::uint32_t s1 = rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
      const std::uint32_t choice = (e & f) ^ ((~e) & g);
      const std::uint32_t temp1 = h + s1 + choice + kRound[index] + words[index];
      const std::uint32_t s0 = rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
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
      block_[block_size_++] = static_cast<std::uint8_t>(original_bits >> shift);
    }
    transform(block_.data());
    std::array<std::uint8_t, 32> result{};
    for (std::size_t index = 0; index < state_.size(); ++index) {
      result[index * 4] = static_cast<std::uint8_t>(state_[index] >> 24);
      result[index * 4 + 1] = static_cast<std::uint8_t>(state_[index] >> 16);
      result[index * 4 + 2] = static_cast<std::uint8_t>(state_[index] >> 8);
      result[index * 4 + 3] = static_cast<std::uint8_t>(state_[index]);
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

// --------------------------- Files and durability --------------------------

std::int64_t mtime_ns(const fs::path& path) {
#ifdef _WIN32
  WIN32_FILE_ATTRIBUTE_DATA data{};
  if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data)) {
    throw ConversionError("cannot stat file time: " + path_text(path));
  }
  ULARGE_INTEGER value{};
  value.LowPart = data.ftLastWriteTime.dwLowDateTime;
  value.HighPart = data.ftLastWriteTime.dwHighDateTime;
  constexpr std::uint64_t kUnixEpochTicks = 116444736000000000ULL;
  if (value.QuadPart < kUnixEpochTicks) {
    throw ConversionError("file timestamp predates Unix epoch: " + path_text(path));
  }
  const std::uint64_t nanoseconds = (value.QuadPart - kUnixEpochTicks) * 100ULL;
  if (nanoseconds > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
    throw ConversionError("file timestamp is out of range: " + path_text(path));
  }
  return static_cast<std::int64_t>(nanoseconds);
#else
  struct stat info{};
  if (::stat(path.c_str(), &info) != 0) {
    throw ConversionError("cannot stat file time: " + path_text(path));
  }
#if defined(__APPLE__)
  return static_cast<std::int64_t>(info.st_mtimespec.tv_sec) * 1'000'000'000LL +
         info.st_mtimespec.tv_nsec;
#else
  return static_cast<std::int64_t>(info.st_mtim.tv_sec) * 1'000'000'000LL +
         info.st_mtim.tv_nsec;
#endif
#endif
}

void flush_file_to_disk(const fs::path& path) {
#ifdef _WIN32
  HANDLE handle = CreateFileW(path.c_str(), GENERIC_WRITE,
                              FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (handle == INVALID_HANDLE_VALUE) {
    throw ConversionError("cannot open for durable flush: " + path_text(path));
  }
  const BOOL ok = FlushFileBuffers(handle);
  CloseHandle(handle);
  if (!ok) throw ConversionError("cannot flush file: " + path_text(path));
#else
  const int descriptor = ::open(path.c_str(), O_RDONLY);
  if (descriptor < 0) throw ConversionError("cannot open for fsync: " + path_text(path));
  const int result = ::fsync(descriptor);
  ::close(descriptor);
  if (result != 0) throw ConversionError("cannot fsync file: " + path_text(path));
#endif
}

void atomic_replace(const fs::path& temporary, const fs::path& destination) {
#ifdef _WIN32
  if (!MoveFileExW(temporary.c_str(), destination.c_str(),
                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
    throw ConversionError("cannot publish " + path_text(destination) +
                          " (Windows error " + std::to_string(GetLastError()) + ")");
  }
#else
  std::error_code error;
  fs::rename(temporary, destination, error);
  if (error) throw ConversionError("cannot publish " + path_text(destination) + ": " + error.message());
#endif
}

void atomic_write_json(const fs::path& path, const Json& payload) {
  fs::create_directories(path.parent_path());
  fs::path temporary = path;
  temporary += ".part";
  {
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) throw ConversionError("cannot create JSON part file: " + path_text(temporary));
    write_json(output, payload, 2);
    output << '\n';
    output.flush();
    if (!output) throw ConversionError("cannot write JSON part file: " + path_text(temporary));
  }
  flush_file_to_disk(temporary);
  atomic_replace(temporary, path);
}

struct Fingerprint {
  std::int64_t size_bytes = 0;
  std::int64_t mtime_nanoseconds = 0;
  std::string sha256;
  std::int64_t lines = 0;

  Json to_json() const {
    return object({{"mtime_ns", mtime_nanoseconds},
                   {"sha256", sha256},
                   {"size_bytes", size_bytes},
                   {"transcript_lines", lines}});
  }

  bool operator==(const Fingerprint& other) const {
    return size_bytes == other.size_bytes &&
           mtime_nanoseconds == other.mtime_nanoseconds &&
           sha256 == other.sha256 && lines == other.lines;
  }
};

Fingerprint fingerprint_file(const fs::path& path) {
  Fingerprint result;
  std::error_code error;
  result.size_bytes = static_cast<std::int64_t>(fs::file_size(path, error));
  if (error) throw ConversionError("cannot stat source: " + path_text(path));
  result.mtime_nanoseconds = mtime_ns(path);
  std::ifstream source(path, std::ios::binary);
  if (!source) throw ConversionError("cannot open source: " + path_text(path));
  Sha256 digest;
  std::array<char, 1 << 20> buffer{};
  bool any = false;
  char last = '\0';
  while (source) {
    source.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize count = source.gcount();
    if (count <= 0) break;
    any = true;
    last = buffer[static_cast<std::size_t>(count - 1)];
    digest.update(buffer.data(), static_cast<std::size_t>(count));
    result.lines += static_cast<std::int64_t>(
        std::count(buffer.begin(), buffer.begin() + count, '\n'));
  }
  if (!source.eof()) throw ConversionError("cannot read source: " + path_text(path));
  if (any && last != '\n') ++result.lines;
  result.sha256 = digest.hex_digest();
  const auto size_after = static_cast<std::int64_t>(fs::file_size(path, error));
  if (error || size_after != result.size_bytes || mtime_ns(path) != result.mtime_nanoseconds) {
    throw ConversionError("source changed while fingerprinting: " + path_text(path));
  }
  return result;
}

// ------------------------------- Split hash --------------------------------

struct DecimalRatio {
  std::uint64_t numerator = 0;
  unsigned scale = 0;
  std::string text;
};

std::uint64_t power10(unsigned exponent) {
  std::uint64_t result = 1;
  for (unsigned index = 0; index < exponent; ++index) {
    if (result > std::numeric_limits<std::uint64_t>::max() / 10) {
      throw ConversionError("split ratio has too many decimal places");
    }
    result *= 10;
  }
  return result;
}

DecimalRatio parse_decimal_ratio(const std::string& raw) {
  if (raw.empty()) throw ConversionError("split ratio is empty");
  const std::size_t dot = raw.find('.');
  if (dot != std::string::npos && raw.find('.', dot + 1) != std::string::npos) {
    throw ConversionError("invalid split ratio: " + raw);
  }
  std::string integer = dot == std::string::npos ? raw : raw.substr(0, dot);
  std::string fraction = dot == std::string::npos ? "" : raw.substr(dot + 1);
  if (integer.empty()) integer = "0";
  if ((integer != "0" && integer != "1") ||
      !std::all_of(fraction.begin(), fraction.end(), [](unsigned char ch) { return std::isdigit(ch); })) {
    throw ConversionError("split ratio must be a decimal between 0 and 1: " + raw);
  }
  while (!fraction.empty() && fraction.back() == '0') fraction.pop_back();
  if (fraction.size() > 18) throw ConversionError("split ratio supports at most 18 decimal places");
  const std::uint64_t denominator = power10(static_cast<unsigned>(fraction.size()));
  std::uint64_t numerator = integer == "1" ? denominator : 0;
  if (!fraction.empty()) {
    if (integer == "1") throw ConversionError("split ratio exceeds 1: " + raw);
    numerator = static_cast<std::uint64_t>(std::stoull(fraction));
  }
  const std::string normalized = integer == "1" ? "1" :
      (fraction.empty() ? "0" : "0." + fraction);
  return DecimalRatio{numerator, static_cast<unsigned>(fraction.size()), normalized};
}

struct SplitConfig {
  std::string seed;
  std::array<DecimalRatio, 3> input;
  std::uint64_t denominator = 1;
  std::array<std::uint64_t, 3> scaled{};

  static SplitConfig create(std::string seed, const std::array<std::string, 3>& values) {
    SplitConfig result;
    result.seed = std::move(seed);
    unsigned scale = 0;
    for (std::size_t index = 0; index < 3; ++index) {
      result.input[index] = parse_decimal_ratio(values[index]);
      scale = std::max(scale, result.input[index].scale);
    }
    result.denominator = power10(scale);
    std::uint64_t sum = 0;
    for (std::size_t index = 0; index < 3; ++index) {
      result.scaled[index] = result.input[index].numerator *
                             power10(scale - result.input[index].scale);
      if (sum > std::numeric_limits<std::uint64_t>::max() - result.scaled[index]) {
        throw ConversionError("split ratio sum is out of range");
      }
      sum += result.scaled[index];
    }
    if (sum != result.denominator) {
      throw ConversionError("split ratios must sum exactly to 1");
    }
    return result;
  }

  Json to_json() const {
    return object({
        {"algorithm", kSplitAlgorithm},
        {"ratios", object({{"test", input[2].text},
                            {"train", input[0].text},
                            {"val", input[1].text}})},
        {"seed", seed},
        {"stable_id", kStableId},
        {"unit", kSplitUnit},
    });
  }
};

bool digest_less_than_ratio(const std::array<std::uint8_t, 32>& digest,
                            std::uint64_t numerator,
                            std::uint64_t denominator) {
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
  return std::lexicographical_compare(digest.begin(), digest.end(),
                                      threshold.begin(), threshold.end());
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
          board[static_cast<std::size_t>(y * 8 + (7 - x))];
    }
  }
  return result;
}

std::string canonical_d4(const std::string& board) {
  if (board.size() != 64 ||
      !std::all_of(board.begin(), board.end(), [](char ch) {
        return ch == 'X' || ch == 'O' || ch == '-';
      })) {
    throw ConversionError("internal invalid relative board");
  }
  std::string best;
  std::string rotated = board;
  for (int index = 0; index < 4; ++index) {
    const std::string reflected = mirror(rotated);
    if (best.empty() || rotated < best) best = rotated;
    if (reflected < best) best = reflected;
    rotated = rotate90(rotated);
  }
  return best;
}

int assign_split(const std::string& board, const SplitConfig& config) {
  const std::string key = canonical_d4(board);
  std::string material = "Egaroucid-v0002-split";
  material.push_back('\0');
  material += config.seed;
  material.push_back('\0');
  material += key;
  Sha256 hash;
  hash.update(material);
  const auto digest = hash.digest();
  if (digest_less_than_ratio(digest, config.scaled[0], config.denominator)) return 0;
  const std::uint64_t validation_end = config.scaled[0] + config.scaled[1];
  if (digest_less_than_ratio(digest, validation_end, config.denominator)) return 1;
  return 2;
}

// ------------------------------ Othello replay -----------------------------

constexpr std::uint64_t kFileA = 0x0101010101010101ULL;
constexpr std::uint64_t kFileH = 0x8080808080808080ULL;

std::uint64_t shift_bits(std::uint64_t bits, int direction) {
  switch (direction) {
    case 0: return (bits & ~kFileA) >> 1;       // west
    case 1: return (bits & ~kFileH) << 1;       // east
    case 2: return bits >> 8;                   // north
    case 3: return bits << 8;                   // south
    case 4: return (bits & ~kFileA) >> 9;
    case 5: return (bits & ~kFileH) >> 7;
    case 6: return (bits & ~kFileA) << 7;
    case 7: return (bits & ~kFileH) << 9;
    default: return 0;
  }
}

std::uint64_t flips_for_move(std::uint64_t move, std::uint64_t own,
                             std::uint64_t opponent) {
  if ((move & (own | opponent)) != 0 || move == 0) return 0;
  std::uint64_t flips = 0;
  for (int direction = 0; direction < 8; ++direction) {
    std::uint64_t cursor = shift_bits(move, direction);
    std::uint64_t captured = 0;
    while ((cursor & opponent) != 0) {
      captured |= cursor;
      cursor = shift_bits(cursor, direction);
    }
    if ((cursor & own) != 0) flips |= captured;
  }
  return flips;
}

std::uint64_t legal_moves(std::uint64_t own, std::uint64_t opponent) {
  const std::uint64_t empty = ~(own | opponent);
  std::uint64_t moves = 0;
  for (int direction = 0; direction < 8; ++direction) {
    std::uint64_t ray = shift_bits(own, direction) & opponent;
    std::uint64_t reached = ray;
    while (ray != 0) {
      ray = shift_bits(ray, direction) & opponent;
      const std::uint64_t added = ray & ~reached;
      reached |= ray;
      if (added == 0) break;
    }
    moves |= shift_bits(reached, direction) & empty;
  }
  return moves;
}

int popcount(std::uint64_t value) {
#if defined(_MSC_VER)
  return static_cast<int>(__popcnt64(value));
#else
  return __builtin_popcountll(value);
#endif
}

struct Board {
  std::uint64_t black = 0;
  std::uint64_t white = 0;
};

Board initial_board() {
  Board board;
  board.white |= 1ULL << (3 + 3 * 8);  // d4
  board.black |= 1ULL << (4 + 3 * 8);  // e4
  board.black |= 1ULL << (3 + 4 * 8);  // d5
  board.white |= 1ULL << (4 + 4 * 8);  // e5
  return board;
}

std::uint64_t own_bits(const Board& board, bool black) {
  return black ? board.black : board.white;
}

std::uint64_t opponent_bits(const Board& board, bool black) {
  return black ? board.white : board.black;
}

void apply_move(Board& board, int cell, bool black) {
  const std::uint64_t move = 1ULL << cell;
  std::uint64_t own = own_bits(board, black);
  std::uint64_t opponent = opponent_bits(board, black);
  const std::uint64_t flips = flips_for_move(move, own, opponent);
  if (flips == 0) throw ConversionError("internal illegal move application");
  own |= move | flips;
  opponent &= ~flips;
  if (black) {
    board.black = own;
    board.white = opponent;
  } else {
    board.white = own;
    board.black = opponent;
  }
}

std::string relative_board(const Board& board, bool black_to_move) {
  const std::uint64_t own = own_bits(board, black_to_move);
  const std::uint64_t opponent = opponent_bits(board, black_to_move);
  std::string result(64, '-');
  for (int cell = 0; cell < 64; ++cell) {
    const std::uint64_t bit = 1ULL << cell;
    if (own & bit) result[static_cast<std::size_t>(cell)] = 'X';
    else if (opponent & bit) result[static_cast<std::size_t>(cell)] = 'O';
  }
  return result;
}

int terminal_score(const Board& board, bool sampled_black) {
  const int own = popcount(own_bits(board, sampled_black));
  const int opponent = popcount(opponent_bits(board, sampled_black));
  const int difference = own - opponent;
  const int empty = 64 - own - opponent;
  if (difference > 0) return difference + empty;
  if (difference < 0) return difference - empty;
  return 0;
}

std::string coordinate(int cell) {
  std::string result;
  result.push_back(static_cast<char>('a' + cell % 8));
  result.push_back(static_cast<char>('1' + cell / 8));
  return result;
}

std::vector<int> parse_transcript(const std::string& raw,
                                  const fs::path& path,
                                  std::int64_t line_number) {
  std::string line = raw;
  while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) {
    line.pop_back();
  }
  const std::string location = path_text(path) + ":" + std::to_string(line_number);
  if (line.empty() || line.size() % 2 != 0) {
    throw ConversionError(location +
                          ": transcript must be contiguous lowercase coordinates a1..h8");
  }
  std::vector<int> moves;
  moves.reserve(line.size() / 2);
  for (std::size_t offset = 0; offset < line.size(); offset += 2) {
    const unsigned char file = static_cast<unsigned char>(line[offset]);
    const unsigned char rank = static_cast<unsigned char>(line[offset + 1]);
    if (file < 'a' || file > 'h' || rank < '1' || rank > '8') {
      throw ConversionError(location +
                            ": transcript must be contiguous lowercase coordinates a1..h8");
    }
    moves.push_back(static_cast<int>((rank - '1') * 8 + (file - 'a')));
  }
  return moves;
}

struct Example {
  std::string board;
  int score = 0;
};

std::optional<Example> replay_transcript(const std::vector<int>& transcript,
                                         int random_plies,
                                         const fs::path& path,
                                         std::int64_t line_number) {
  const std::string location = path_text(path) + ":" + std::to_string(line_number);
  if (transcript.size() < static_cast<std::size_t>(random_plies)) {
    throw ConversionError(location + ": transcript has " +
                          std::to_string(transcript.size()) +
                          " placement plies, fewer than its random prefix " +
                          std::to_string(random_plies));
  }
  Board board = initial_board();
  bool black = true;
  std::optional<std::string> sampled_board;
  bool sampled_black = true;
  bool no_training_position = false;

  for (std::size_t index = 0; index < transcript.size(); ++index) {
    const int move = transcript[index];
    std::uint64_t legal = legal_moves(own_bits(board, black), opponent_bits(board, black));
    if (legal == 0) {
      const std::uint64_t other = legal_moves(own_bits(board, !black), opponent_bits(board, !black));
      if (other == 0) {
        throw ConversionError(location + ": move " + std::to_string(index + 1) +
                              " (" + coordinate(move) + ") occurs after game end");
      }
      black = !black;
      legal = other;
    }
    if ((legal & (1ULL << move)) == 0) {
      throw ConversionError(location + ": illegal move " + std::to_string(index + 1) +
                            " (" + coordinate(move) + ") for " +
                            (black ? "black" : "white"));
    }
    apply_move(board, move, black);
    black = !black;

    if (index + 1 == static_cast<std::size_t>(random_plies)) {
      const std::uint64_t next = legal_moves(own_bits(board, black), opponent_bits(board, black));
      if (next == 0) {
        const std::uint64_t other = legal_moves(own_bits(board, !black), opponent_bits(board, !black));
        if (other == 0) no_training_position = true;
        else black = !black;
      }
      if (!no_training_position) {
        sampled_black = black;
        sampled_board = relative_board(board, black);
      }
    }
  }

  if (legal_moves(own_bits(board, black), opponent_bits(board, black)) != 0 ||
      legal_moves(own_bits(board, !black), opponent_bits(board, !black)) != 0) {
    throw ConversionError(location + ": incomplete game after " +
                          std::to_string(transcript.size()) + " placement plies");
  }
  if (no_training_position) return std::nullopt;
  if (!sampled_board) throw ConversionError(location + ": random-prefix position was not reached");
  return Example{*sampled_board, terminal_score(board, sampled_black)};
}

// -------------------------- Discovery and metadata -------------------------

struct GameFile {
  fs::path path;
  int random_plies = 0;
  int part = 0;
  std::string relative_path;
  std::string source_id;
};

struct Dataset {
  std::array<fs::path, 2> roots;
  std::vector<GameFile> files;
};

bool is_decimal_name(const std::string& value) {
  return !value.empty() &&
         std::all_of(value.begin(), value.end(), [](unsigned char ch) { return std::isdigit(ch); });
}

Dataset discover_dataset(const fs::path& raw_root0, const fs::path& raw_root1) {
  Dataset dataset;
  dataset.roots = {fs::absolute(raw_root0).lexically_normal(),
                   fs::absolute(raw_root1).lexically_normal()};
  if (!fs::is_directory(dataset.roots[0]) || !fs::is_directory(dataset.roots[1])) {
    throw ConversionError("both dataset roots must be existing directories");
  }
  if (dataset.roots[0] == dataset.roots[1]) {
    throw ConversionError("the two dataset roots resolve to the same directory");
  }
  struct PlyDirectory { fs::path path; int part; };
  std::map<int, PlyDirectory> ply_directories;
  for (int part = 0; part < 2; ++part) {
    for (const auto& entry : fs::recursive_directory_iterator(dataset.roots[part])) {
      if (!entry.is_directory()) continue;
      const std::string name = entry.path().filename().string();
      if (!is_decimal_name(name)) continue;
      const int ply = std::stoi(name);
      if (ply < kMinRandomPlies || ply > kMaxRandomPlies) continue;
      if (!ply_directories.emplace(ply, PlyDirectory{entry.path(), part}).second) {
        throw ConversionError("random-ply directory occurs more than once: " +
                              std::to_string(ply));
      }
    }
  }
  for (int ply = kMinRandomPlies; ply <= kMaxRandomPlies; ++ply) {
    const auto directory = ply_directories.find(ply);
    if (directory == ply_directories.end()) {
      throw ConversionError("missing random-ply directory: " + std::to_string(ply));
    }
    std::vector<fs::path> files;
    for (const auto& entry : fs::recursive_directory_iterator(directory->second.path)) {
      if (entry.is_regular_file() && ascii_lower(entry.path().extension().string()) == ".txt") {
        files.push_back(fs::absolute(entry.path()).lexically_normal());
      }
    }
    std::sort(files.begin(), files.end(), [](const fs::path& left, const fs::path& right) {
      const std::string left_text = generic_path_text(left);
      const std::string right_text = generic_path_text(right);
      const std::string left_folded = ascii_lower(left_text);
      const std::string right_folded = ascii_lower(right_text);
      return left_folded != right_folded ? left_folded < right_folded : left_text < right_text;
    });
    if (files.empty()) {
      throw ConversionError("random-ply directory has no text files: " +
                            path_text(directory->second.path));
    }
    for (const fs::path& path : files) {
      const int part = directory->second.part;
      const fs::path relative = fs::relative(path, dataset.roots[part]);
      const std::string relative_text = generic_path_text(relative);
      dataset.files.push_back(GameFile{path, ply, part, relative_text,
                                       "part" + std::to_string(part) + "/" + relative_text});
    }
  }
  return dataset;
}

struct ShardInfo {
  std::string relative_path;
  std::int64_t rows = 0;
  std::int64_t size_bytes = 0;
  std::string sha256;

  Json to_json() const {
    return object({{"path", relative_path}, {"rows", rows},
                   {"sha256", sha256}, {"size_bytes", size_bytes}});
  }
};

bool valid_integer_score(const std::string& score) {
  if (score == "0") return true;
  std::size_t index = 0;
  if (!score.empty() && score[0] == '-') index = 1;
  if (index >= score.size() || score[index] < '1' || score[index] > '9') return false;
  return std::all_of(score.begin() + static_cast<std::ptrdiff_t>(index + 1), score.end(),
                     [](unsigned char ch) { return std::isdigit(ch); });
}

ShardInfo scan_shard(const fs::path& path, const fs::path& output_root) {
  std::ifstream source(path, std::ios::binary);
  if (!source) throw ConversionError("missing output shard: " + path_text(path));
  Sha256 digest;
  std::string line;
  std::int64_t rows = 0;
  std::int64_t bytes = 0;
  while (std::getline(source, line)) {
    ++rows;
    if (line.size() < 66 || line[64] != ' ' ||
        !std::all_of(line.begin(), line.begin() + 64, [](char ch) {
          return ch == 'X' || ch == 'O' || ch == '-';
        })) {
      throw ConversionError("invalid prepared row at " + path_text(path) + ":" +
                            std::to_string(rows));
    }
    const std::string score_text = line.substr(65);
    if (!valid_integer_score(score_text)) {
      throw ConversionError("invalid prepared score at " + path_text(path) + ":" +
                            std::to_string(rows));
    }
    int score = 0;
    try { score = std::stoi(score_text); }
    catch (const std::exception&) {
      throw ConversionError("prepared score out of range at " + path_text(path));
    }
    if (score < -64 || score > 64) {
      throw ConversionError("prepared score out of range at " + path_text(path));
    }
    line.push_back('\n');
    digest.update(line);
    bytes += static_cast<std::int64_t>(line.size());
  }
  if (!source.eof()) throw ConversionError("cannot read output shard: " + path_text(path));
  std::error_code error;
  const auto actual_size = static_cast<std::int64_t>(fs::file_size(path, error));
  if (error || actual_size != bytes) {
    throw ConversionError("prepared shard must use LF line endings: " + path_text(path));
  }
  return ShardInfo{generic_path_text(fs::relative(path, output_root)), rows,
                   bytes, digest.hex_digest()};
}

fs::path output_path(const fs::path& output_root, const GameFile& game, int split) {
  return output_root / kSplitNames[static_cast<std::size_t>(split)] /
         std::to_string(game.random_plies) / (game.path.stem().string() + ".txt");
}

fs::path receipt_path(const fs::path& output_root, const GameFile& game) {
  return output_root / "_receipts" / std::to_string(game.random_plies) /
         (game.path.stem().string() + ".json");
}

void validate_output_collisions(const std::vector<GameFile>& files,
                                const fs::path& output_root) {
  std::map<std::string, std::string> seen;
  for (const auto& game : files) {
    for (int split = 0; split < 3; ++split) {
      const std::string key = ascii_lower(path_text(fs::absolute(output_path(output_root, game, split))));
      if (!seen.emplace(key, game.source_id).second) {
        throw ConversionError("two sources map to the same output shard: " + game.source_id);
      }
    }
    const std::string key = ascii_lower(path_text(fs::absolute(receipt_path(output_root, game))));
    if (!seen.emplace(key, game.source_id).second) {
      throw ConversionError("two sources map to the same receipt: " + game.source_id);
    }
  }
}

int evaluator_phase(int random_plies) {
  const int phase = ((random_plies + 4) - 4) / 10 - 2;
  return std::max(0, std::min(3, phase));
}

// ------------------------------ Source conversion -------------------------

struct SourceResult {
  Json manifest_source;
  bool resumed = false;
  std::int64_t source_games = 0;
};

std::int64_t int_field(const Json& object_value, const std::string& key) {
  return object_value.at(key).as_int();
}

void require_equal(const Json& actual, const Json& expected,
                   const fs::path& receipt, const std::string& field) {
  if (actual != expected) {
    throw ConversionError("completed receipt does not match source/config at " +
                          path_text(receipt) + ": field " + field + " differs");
  }
}

SourceResult resume_source(const GameFile& game, const fs::path& output_root,
                           const SplitConfig& split_config,
                           const Fingerprint& fingerprint) {
  const fs::path receipt = receipt_path(output_root, game);
  Json payload = read_json(receipt);
  if (!payload.is_object()) throw ConversionError("receipt is not an object: " + path_text(receipt));
  require_equal(payload.at("schema_version"), Json(kReceiptSchema), receipt, "schema_version");
  require_equal(payload.at("status"), Json("complete"), receipt, "status");
  require_equal(payload.at("source_id"), Json(game.source_id), receipt, "source_id");
  require_equal(payload.at("part"), Json(game.part), receipt, "part");
  require_equal(payload.at("relative_path"), Json(game.relative_path), receipt, "relative_path");
  require_equal(payload.at("random_plies"), Json(game.random_plies), receipt, "random_plies");
  require_equal(payload.at("fingerprint"), fingerprint.to_json(), receipt, "fingerprint");
  require_equal(payload.at("split"), split_config.to_json(), receipt, "split");
  const Json& outputs = payload.at("outputs");
  if (!outputs.is_object() || outputs.as_object().size() != 3) {
    throw ConversionError("receipt has invalid outputs: " + path_text(receipt));
  }
  std::int64_t prepared = 0;
  for (int split = 0; split < 3; ++split) {
    const ShardInfo actual = scan_shard(output_path(output_root, game, split), output_root);
    require_equal(outputs.at(kSplitNames[static_cast<std::size_t>(split)]), actual.to_json(),
                  receipt, std::string("outputs.") + kSplitNames[static_cast<std::size_t>(split)]);
    prepared += actual.rows;
  }
  if (int_field(payload, "prepared_records") != prepared ||
      int_field(payload, "source_transcript_lines") != fingerprint.lines ||
      int_field(payload, "skipped_no_position") != fingerprint.lines - prepared) {
    throw ConversionError("receipt has inconsistent game counts: " + path_text(receipt));
  }
  payload["receipt_path"] = generic_path_text(fs::relative(receipt, output_root));
  payload["run_action"] = "validated-and-skipped";
  return SourceResult{std::move(payload), true, fingerprint.lines};
}

SourceResult convert_source(const GameFile& game, const fs::path& output_root,
                            const SplitConfig& split_config,
                            const Fingerprint& fingerprint) {
  std::array<fs::path, 3> final_paths;
  std::array<fs::path, 3> part_paths;
  std::array<bool, 3> existing{};
  std::array<std::optional<ShardInfo>, 3> existing_info;
  std::array<std::unique_ptr<std::ofstream>, 3> writers;
  std::array<Sha256, 3> hashes;
  std::array<std::int64_t, 3> counts{};
  for (int split = 0; split < 3; ++split) {
    final_paths[split] = output_path(output_root, game, split);
    part_paths[split] = final_paths[split];
    part_paths[split] += ".part";
    existing[split] = fs::is_regular_file(final_paths[split]);
    if (existing[split]) {
      existing_info[split] = scan_shard(final_paths[split], output_root);
    } else {
      fs::create_directories(final_paths[split].parent_path());
      writers[split] = std::make_unique<std::ofstream>(
          part_paths[split], std::ios::binary | std::ios::trunc);
      if (!*writers[split]) {
        throw ConversionError("cannot create output part: " + path_text(part_paths[split]));
      }
    }
  }

  std::ifstream source(game.path, std::ios::binary);
  if (!source) throw ConversionError("cannot open transcript file: " + path_text(game.path));
  std::string raw;
  std::int64_t line_number = 0;
  std::int64_t skipped = 0;
  while (std::getline(source, raw)) {
    ++line_number;
    const auto transcript = parse_transcript(raw, game.path, line_number);
    const auto example = replay_transcript(transcript, game.random_plies, game.path, line_number);
    if (!example) {
      ++skipped;
      continue;
    }
    const int split = assign_split(example->board, split_config);
    const std::string row = example->board + " " + std::to_string(example->score) + "\n";
    hashes[split].update(row);
    ++counts[split];
    if (writers[split]) {
      writers[split]->write(row.data(), static_cast<std::streamsize>(row.size()));
      if (!*writers[split]) {
        throw ConversionError("cannot write output part: " + path_text(part_paths[split]));
      }
    }
  }
  if (!source.eof()) throw ConversionError("cannot read transcript file: " + path_text(game.path));
  if (line_number != fingerprint.lines) {
    throw ConversionError("source line count changed while replaying: " + path_text(game.path));
  }
  for (int split = 0; split < 3; ++split) {
    if (writers[split]) {
      writers[split]->flush();
      if (!*writers[split]) throw ConversionError("cannot flush output: " + path_text(part_paths[split]));
      writers[split]->close();
      flush_file_to_disk(part_paths[split]);
    }
  }
  const Fingerprint after = fingerprint_file(game.path);
  if (!(after == fingerprint)) {
    throw ConversionError("source changed while replaying: " + path_text(game.path));
  }
  for (int split = 0; split < 3; ++split) {
    if (existing[split]) {
      if (existing_info[split]->rows != counts[split] ||
          existing_info[split]->sha256 != hashes[split].hex_digest()) {
        throw ConversionError("existing shard does not match replay: " + path_text(final_paths[split]));
      }
    } else {
      atomic_replace(part_paths[split], final_paths[split]);
    }
  }

  std::array<ShardInfo, 3> published;
  for (int split = 0; split < 3; ++split) {
    published[split] = scan_shard(final_paths[split], output_root);
    if (published[split].rows != counts[split] ||
        published[split].sha256 != hashes[split].hex_digest()) {
      throw ConversionError("published shard failed validation: " + path_text(final_paths[split]));
    }
    std::error_code ignored;
    fs::remove(part_paths[split], ignored);
  }
  const std::int64_t prepared = counts[0] + counts[1] + counts[2];
  if (prepared + skipped != fingerprint.lines) {
    throw ConversionError("converted counts do not conserve source games: " + path_text(game.path));
  }
  Json receipt = object({
      {"fingerprint", fingerprint.to_json()},
      {"outputs", object({{"test", published[2].to_json()},
                           {"train", published[0].to_json()},
                           {"val", published[1].to_json()}})},
      {"part", game.part},
      {"prepared_records", prepared},
      {"random_plies", game.random_plies},
      {"relative_path", game.relative_path},
      {"schema_version", kReceiptSchema},
      {"skipped_no_position", skipped},
      {"source_id", game.source_id},
      {"source_transcript_lines", fingerprint.lines},
      {"split", split_config.to_json()},
      {"status", "complete"},
  });
  const fs::path receipt_file = receipt_path(output_root, game);
  atomic_write_json(receipt_file, receipt);
  receipt["receipt_path"] = generic_path_text(fs::relative(receipt_file, output_root));
  receipt["run_action"] = "converted";
  return SourceResult{std::move(receipt), false, fingerprint.lines};
}

SourceResult process_source(const GameFile& game, const fs::path& output_root,
                            const SplitConfig& split_config,
                            std::int64_t expected_games_per_file) {
  const Fingerprint fingerprint = fingerprint_file(game.path);
  if (fingerprint.lines != expected_games_per_file) {
    throw ConversionError("source game count mismatch for " + path_text(game.path) +
                          ": expected " + std::to_string(expected_games_per_file) +
                          ", got " + std::to_string(fingerprint.lines));
  }
  const fs::path receipt = receipt_path(output_root, game);
  if (fs::is_regular_file(receipt)) {
    return resume_source(game, output_root, split_config, fingerprint);
  }
  return convert_source(game, output_root, split_config, fingerprint);
}

// -------------------------------- Progress ---------------------------------

std::string duration_text(double seconds) {
  if (!std::isfinite(seconds) || seconds < 0) return "--:--";
  const auto total = static_cast<std::int64_t>(seconds);
  const auto hours = total / 3600;
  const auto minutes = (total % 3600) / 60;
  const auto remainder = total % 60;
  std::ostringstream result;
  result << std::setfill('0');
  if (hours > 0) result << std::setw(2) << hours << ':';
  result << std::setw(2) << minutes << ':' << std::setw(2) << remainder;
  return result.str();
}

class Progress {
 public:
  Progress(std::size_t total_files, std::int64_t total_games,
           std::int64_t expected_resume_games, double interval, bool quiet,
           int workers)
      : total_files_(total_files), total_games_(total_games),
        expected_resume_games_(expected_resume_games), interval_(interval),
        quiet_(quiet), workers_(workers), started_(Clock::now()),
        last_(started_ - std::chrono::duration_cast<Clock::duration>(
                             std::chrono::duration<double>(interval))) {
#ifdef _WIN32
    tty_ = _isatty(_fileno(stderr)) != 0;
#else
    tty_ = isatty(fileno(stderr)) != 0;
#endif
  }

  void complete(const SourceResult& result) {
    std::lock_guard<std::mutex> lock(mutex_);
    ++files_done_;
    games_done_ += result.source_games;
    if (result.resumed) resumed_games_ += result.source_games;
    else converted_games_ += result.source_games;
    render(false);
  }

  void finish() {
    std::lock_guard<std::mutex> lock(mutex_);
    render(true);
    if (tty_ && !quiet_) std::cerr << '\n';
  }

 private:
  using Clock = std::chrono::steady_clock;

  void render(bool force) {
    if (quiet_) return;
    const auto now = Clock::now();
    const double since_last = std::chrono::duration<double>(now - last_).count();
    if (!force && since_last < interval_) return;
    last_ = now;
    const double elapsed = std::chrono::duration<double>(now - started_).count();
    const double rate = elapsed > 0 ? converted_games_ / elapsed : 0.0;
    const std::int64_t expected_new = std::max<std::int64_t>(
        0, total_games_ - expected_resume_games_);
    const std::int64_t remaining_new = std::max<std::int64_t>(0, expected_new - converted_games_);
    const double eta = rate > 0 ? remaining_new / rate : std::numeric_limits<double>::quiet_NaN();
    const double fraction = total_games_ > 0
        ? static_cast<double>(games_done_) / total_games_ : 1.0;
    const int filled = std::max(0, std::min(24, static_cast<int>(fraction * 24)));
    std::ostringstream line;
    line << "[convert " << files_done_ << '/' << total_files_ << " workers=" << workers_ << "] ";
    if (tty_) line << '[' << std::string(filled, '#') << std::string(24 - filled, '.') << "] | ";
    line << games_done_ << '/' << total_games_ << " (" << std::fixed << std::setprecision(1)
         << fraction * 100.0 << "%) | " << std::setprecision(0) << rate
         << " new items/s | " << duration_text(elapsed) << " elapsed | "
         << duration_text(eta) << " ETA";
    if (tty_) {
      const std::string text = line.str();
      std::cerr << '\r' << text;
      if (text.size() < previous_width_) std::cerr << std::string(previous_width_ - text.size(), ' ');
      previous_width_ = text.size();
      std::cerr.flush();
    } else {
      std::cerr << line.str() << '\n';
    }
  }

  std::size_t total_files_;
  std::int64_t total_games_;
  std::int64_t expected_resume_games_;
  double interval_;
  bool quiet_;
  int workers_;
  bool tty_ = false;
  std::mutex mutex_;
  std::size_t files_done_ = 0;
  std::int64_t games_done_ = 0;
  std::int64_t resumed_games_ = 0;
  std::int64_t converted_games_ = 0;
  Clock::time_point started_;
  Clock::time_point last_;
  std::size_t previous_width_ = 0;
};

// ------------------------------ Manifest -----------------------------------

Json counter_json(const std::map<int, std::int64_t>& values) {
  Json::Object result;
  for (const auto& [key, value] : values) result[std::to_string(key)] = value;
  return Json(std::move(result));
}

struct AggregatedCounts {
  Json json;
  std::int64_t source_games = 0;
  std::int64_t prepared = 0;
  std::int64_t skipped = 0;
  std::array<std::int64_t, 3> by_split{};
  std::map<int, std::int64_t> source_by_random;
  std::map<int, std::int64_t> prepared_by_random;
  std::map<int, std::int64_t> skipped_by_random;
  std::array<std::map<int, std::int64_t>, 3> split_by_random;
  std::map<int, std::int64_t> source_by_phase;
  std::map<int, std::int64_t> prepared_by_phase;
  std::map<int, std::int64_t> skipped_by_phase;
  std::array<std::map<int, std::int64_t>, 3> split_by_phase;
};

AggregatedCounts aggregate(const std::vector<SourceResult>& results) {
  AggregatedCounts counts;
  for (const auto& result : results) {
    const Json& source = result.manifest_source;
    const int ply = static_cast<int>(int_field(source, "random_plies"));
    const int phase = evaluator_phase(ply);
    const std::int64_t source_games = int_field(source, "source_transcript_lines");
    const std::int64_t prepared = int_field(source, "prepared_records");
    const std::int64_t skipped = int_field(source, "skipped_no_position");
    counts.source_games += source_games;
    counts.prepared += prepared;
    counts.skipped += skipped;
    counts.source_by_random[ply] += source_games;
    counts.prepared_by_random[ply] += prepared;
    counts.skipped_by_random[ply] += skipped;
    counts.source_by_phase[phase] += source_games;
    counts.prepared_by_phase[phase] += prepared;
    counts.skipped_by_phase[phase] += skipped;
    const Json& outputs = source.at("outputs");
    for (int split = 0; split < 3; ++split) {
      const std::int64_t rows = int_field(
          outputs.at(kSplitNames[static_cast<std::size_t>(split)]), "rows");
      counts.by_split[split] += rows;
      counts.split_by_random[split][ply] += rows;
      counts.split_by_phase[split][phase] += rows;
    }
  }
  counts.json = object({
      {"by_split", object({{"test", counts.by_split[2]},
                            {"train", counts.by_split[0]},
                            {"val", counts.by_split[1]}})},
      {"by_split_and_phase", object({{"test", counter_json(counts.split_by_phase[2])},
                                      {"train", counter_json(counts.split_by_phase[0])},
                                      {"val", counter_json(counts.split_by_phase[1])}})},
      {"by_split_and_random_plies", object({{"test", counter_json(counts.split_by_random[2])},
                                             {"train", counter_json(counts.split_by_random[0])},
                                             {"val", counter_json(counts.split_by_random[1])}})},
      {"output_shards", static_cast<std::int64_t>(results.size() * 3)},
      {"prepared_records", counts.prepared},
      {"prepared_records_by_phase", counter_json(counts.prepared_by_phase)},
      {"prepared_records_by_random_plies", counter_json(counts.prepared_by_random)},
      {"skipped_no_position", counts.skipped},
      {"skipped_no_position_by_phase", counter_json(counts.skipped_by_phase)},
      {"skipped_no_position_by_random_plies", counter_json(counts.skipped_by_random)},
      {"source_files", static_cast<std::int64_t>(results.size())},
      {"source_games", counts.source_games},
      {"source_games_by_phase", counter_json(counts.source_by_phase)},
      {"source_games_by_random_plies", counter_json(counts.source_by_random)},
  });
  return counts;
}

void verify_full_input(const std::vector<GameFile>& files) {
  if (files.size() != static_cast<std::size_t>(kExpectedSourceFiles)) {
    throw ConversionError("official dataset must contain 5,200 source files; got " +
                          std::to_string(files.size()));
  }
  std::map<int, int> by_ply;
  for (const auto& file : files) ++by_ply[file.random_plies];
  for (int ply = kMinRandomPlies; ply <= kMaxRandomPlies; ++ply) {
    if (by_ply[ply] != kExpectedFilesPerPly) {
      throw ConversionError("random-ply " + std::to_string(ply) +
                            " must contain exactly 100 files");
    }
  }
}

void verify_full_counts(const AggregatedCounts& counts) {
  if (counts.source_games != kExpectedSourceGames ||
      counts.prepared + counts.skipped != counts.source_games) {
    throw ConversionError("full conversion does not conserve 52,000,000 source games");
  }
  for (int ply = kMinRandomPlies; ply <= kMaxRandomPlies; ++ply) {
    const auto source = counts.source_by_random.find(ply);
    if (source == counts.source_by_random.end() || source->second != kExpectedGamesPerPly) {
      throw ConversionError("random-ply source count mismatch: " + std::to_string(ply));
    }
    if (counts.prepared_by_random.at(ply) + counts.skipped_by_random.at(ply) !=
        kExpectedGamesPerPly) {
      throw ConversionError("random-ply conservation mismatch: " + std::to_string(ply));
    }
  }
  const std::map<int, std::int64_t> expected_phases = {
      {0, 22'000'000}, {1, 10'000'000}, {2, 10'000'000}, {3, 10'000'000}};
  if (counts.source_by_phase != expected_phases) {
    throw ConversionError("source phase counts differ from official expectations");
  }
  for (int phase = 0; phase < 4; ++phase) {
    if (counts.prepared_by_phase.at(phase) + counts.skipped_by_phase.at(phase) !=
        expected_phases.at(phase)) {
      throw ConversionError("phase conservation mismatch: " + std::to_string(phase));
    }
  }
}

// ---------------------------------- CLI ------------------------------------

struct Options {
  fs::path root0 = fs::path("resources") / "Egaroucid_Train_Data_v0002_0";
  fs::path root1 = fs::path("resources") / "Egaroucid_Train_Data_v0002_1";
  fs::path output_root = fs::path("data") / "processed" / "egaroucid_v2";
  std::optional<fs::path> manifest;
  std::string split_seed = "20260715";
  std::array<std::string, 3> ratios = {"0.9", "0.05", "0.05"};
  int workers = 12;
  std::optional<std::size_t> limit_files;
  std::int64_t expected_games_per_file = kExpectedGamesPerFile;
  double progress_interval = 1.0;
  bool quiet = false;
  bool self_test = false;
  bool help = false;
};

void print_usage(std::ostream& output) {
  output <<
      "Usage: egaroucid_v2_converter.exe [ROOT_0 ROOT_1] [options]\n"
      "\n"
      "Options:\n"
      "  --output-root PATH              prepared shard directory\n"
      "  --manifest PATH                 manifest path (default OUTPUT_ROOT/conversion_manifest.json)\n"
      "  --split-seed TEXT               default 20260715\n"
      "  --train-ratio DECIMAL           default 0.9\n"
      "  --val-ratio DECIMAL             default 0.05\n"
      "  --test-ratio DECIMAL            default 0.05\n"
      "  --workers N                     parallel source files (default 12)\n"
      "  --limit-files N                 limited smoke conversion; manifest is not trainable\n"
      "  --expected-games-per-file N     test-only count override; manifest is not trainable\n"
      "  --progress-interval SECONDS     default 1\n"
      "  --quiet                         suppress CUI progress\n"
      "  --self-test                     run dependency-free algorithm checks only\n"
      "  --help                          show this help\n";
}

std::int64_t parse_positive(const std::string& value, const std::string& option) {
  try {
    std::size_t used = 0;
    const std::int64_t result = std::stoll(value, &used);
    if (used != value.size() || result <= 0) throw std::invalid_argument("range");
    return result;
  } catch (const std::exception&) {
    throw ConversionError(option + " requires a positive integer");
  }
}

Options parse_options(int argc, char** argv) {
  Options options;
  std::vector<std::string> positional;
  auto require_value = [&](int& index, const std::string& option) -> std::string {
    if (index + 1 >= argc) throw ConversionError(option + " requires a value");
    return argv[++index];
  };
  for (int index = 1; index < argc; ++index) {
    const std::string argument = argv[index];
    if (argument == "--output-root") options.output_root = require_value(index, argument);
    else if (argument == "--manifest") options.manifest = fs::path(require_value(index, argument));
    else if (argument == "--split-seed") options.split_seed = require_value(index, argument);
    else if (argument == "--train-ratio") options.ratios[0] = require_value(index, argument);
    else if (argument == "--val-ratio") options.ratios[1] = require_value(index, argument);
    else if (argument == "--test-ratio") options.ratios[2] = require_value(index, argument);
    else if (argument == "--workers" || argument == "--threads") {
      options.workers = static_cast<int>(parse_positive(require_value(index, argument), argument));
    } else if (argument == "--limit-files") {
      options.limit_files = static_cast<std::size_t>(parse_positive(require_value(index, argument), argument));
    } else if (argument == "--expected-games-per-file") {
      options.expected_games_per_file = parse_positive(require_value(index, argument), argument);
    } else if (argument == "--progress-interval") {
      const std::string value = require_value(index, argument);
      try {
        std::size_t used = 0;
        options.progress_interval = std::stod(value, &used);
        if (used != value.size() || options.progress_interval < 0) throw std::invalid_argument("range");
      } catch (const std::exception&) {
        throw ConversionError(argument + " requires a non-negative number");
      }
    } else if (argument == "--quiet") options.quiet = true;
    else if (argument == "--self-test") options.self_test = true;
    else if (argument == "--help" || argument == "-h") options.help = true;
    else if (!argument.empty() && argument[0] == '-') throw ConversionError("unknown option: " + argument);
    else positional.push_back(argument);
  }
  if (!positional.empty() && positional.size() != 2) {
    throw ConversionError("supply either zero or two dataset roots");
  }
  if (positional.size() == 2) {
    options.root0 = positional[0];
    options.root1 = positional[1];
  }
  options.workers = std::max(1, std::min(options.workers, 64));
  return options;
}

void require_test(bool condition, const std::string& message) {
  if (!condition) throw ConversionError("self-test failed: " + message);
}

void run_self_test() {
  require_test(sha256_text("") ==
                   "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
               "SHA-256 empty");
  require_test(sha256_text("abc") ==
                   "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
               "SHA-256 abc");
  const std::string full_game =
      "c4e3f2e2f4c5c6g4f5e6d3c3c2d6f1b5a6b4a5b6f3a3b3c1d2e1c7d1"
      "b1g3d7a4a2e7g2d8h3b8f8f6g7g6h5h8g5h4h7h6f7e8g8b2c8a7b7a1"
      "a8g1h2h1";
  const auto transcript = parse_transcript(full_game, fs::path("self-test.txt"), 1);
  const auto example = replay_transcript(transcript, 8, fs::path("self-test.txt"), 1);
  require_test(example.has_value(), "full game emitted");
  require_test(example->board ==
                   "------------OX------O-----XOOOO---XXO-----X---------------------",
               "full game board");
  require_test(example->score == -4, "full game score");
  const std::string row = example->board + " -4\n";
  require_test(sha256_text(row) ==
                   "ed855af8fc2483de7835afebb77f45960ca6b897aaad84ba9c23a373435bd631",
               "golden row hash");
  require_test(canonical_d4(example->board) ==
                   "---------------------X-----OXX---OOOOX-----O------XO------------",
               "D4 canonical board");

  const std::string pass_game =
      "c4c3e6c5b4a5c2e3a4a3b5d2d3f4f2b2g4b6c1d6c7h4f5d1e2b8a1f3"
      "c6a2e1b3c8g6g5d8g7b7a7d7g3h3h2g2a6g8e7e8h6f6h1f1h7a8b1g1"
      "h5f7f8h8";
  const auto pass_example = replay_transcript(
      parse_transcript(pass_game, fs::path("self-test-pass.txt"), 1), 55,
      fs::path("self-test-pass.txt"), 1);
  require_test(pass_example.has_value(), "forced-pass game emitted");
  require_test(pass_example->board ==
                   "XXXXXO-XXXXOOOOXXXOXOOOOXXXOXXOOXXXOOXO-XXOXOOXXXOXOO-OXOOOOO-O-",
               "forced-pass boundary board");
  require_test(pass_example->score == 10, "forced-pass score");

  const std::string early_terminal_game =
      "d3c3e6e3c4c5b5c6e2f4d7a5g3c2c1e8a6d6c7f5g5b1a1b2a3c8f3f1"
      "d8f6e1a7f8a2b6g8b4h4g6h3h5d1g1h6d2g4e7b8b3f7h7a4f2g2h2g7"
      "h8b7a8";
  const auto early_moves = parse_transcript(
      early_terminal_game, fs::path("self-test-early.txt"), 1);
  const auto early_example = replay_transcript(
      early_moves, 8, fs::path("self-test-early.txt"), 1);
  require_test(early_example.has_value() && early_example->score == 6,
               "terminal empty-square score");
  require_test(!replay_transcript(early_moves, 59,
                                  fs::path("self-test-early.txt"), 1).has_value(),
               "terminal random-prefix skip");

  const SplitConfig split = SplitConfig::create("20260715", {"0.9", "0.05", "0.05"});
  require_test(assign_split("---------------------------------------------------------------X", split) == 0,
               "train split branch");
  require_test(assign_split("----------------------------------------------------------X--X-X", split) == 1,
               "validation split branch");
  require_test(assign_split("-----------------------------------------------------------X---X", split) == 2,
               "test split branch");
  const Json json = object({{"a", 1}, {"b", array({true, "x", nullptr})}});
  require_test(JsonParser(json_text(json)).parse() == json, "JSON round trip");
  std::cout << "SELF-TEST PASS: sha256=yes, replay=yes, pass=yes, terminal=yes, "
               "d4=yes, split=yes, json=yes\n";
}

int run_conversion(const Options& options) {
  const auto started = std::chrono::steady_clock::now();
  const SplitConfig split_config = SplitConfig::create(options.split_seed, options.ratios);
  Dataset dataset = discover_dataset(options.root0, options.root1);
  const std::size_t discovered_files = dataset.files.size();
  if (options.limit_files) {
    if (*options.limit_files > dataset.files.size()) {
      throw ConversionError("--limit-files exceeds discovered source count");
    }
    dataset.files.resize(*options.limit_files);
  }
  const bool full_mode = !options.limit_files &&
                         options.expected_games_per_file == kExpectedGamesPerFile;
  if (full_mode) verify_full_input(dataset.files);
  const fs::path output_root = fs::absolute(options.output_root).lexically_normal();
  const fs::path manifest_path = fs::absolute(
      options.manifest.value_or(output_root / "conversion_manifest.json")).lexically_normal();
  validate_output_collisions(dataset.files, output_root);
  fs::create_directories(output_root);

  std::int64_t expected_resume_games = 0;
  for (const auto& game : dataset.files) {
    if (fs::is_regular_file(receipt_path(output_root, game))) {
      expected_resume_games += options.expected_games_per_file;
    }
  }
  const std::int64_t total_games = static_cast<std::int64_t>(dataset.files.size()) *
                                   options.expected_games_per_file;
  Progress progress(dataset.files.size(), total_games, expected_resume_games,
                    options.progress_interval, options.quiet, options.workers);
  std::vector<std::optional<SourceResult>> slots(dataset.files.size());
  std::atomic<std::size_t> next{0};
  std::atomic<bool> cancelled{false};
  std::mutex error_mutex;
  std::exception_ptr first_error;
  const int worker_count = std::min<int>(options.workers,
                                         static_cast<int>(dataset.files.size()));
  std::vector<std::thread> workers;
  workers.reserve(static_cast<std::size_t>(worker_count));
  for (int worker = 0; worker < worker_count; ++worker) {
    workers.emplace_back([&] {
      while (!cancelled.load(std::memory_order_relaxed)) {
        const std::size_t index = next.fetch_add(1);
        if (index >= dataset.files.size()) return;
        try {
          SourceResult result = process_source(dataset.files[index], output_root,
                                               split_config,
                                               options.expected_games_per_file);
          slots[index] = std::move(result);
          progress.complete(*slots[index]);
        } catch (...) {
          {
            std::lock_guard<std::mutex> lock(error_mutex);
            if (!first_error) first_error = std::current_exception();
          }
          cancelled.store(true, std::memory_order_relaxed);
          return;
        }
      }
    });
  }
  for (auto& worker : workers) worker.join();
  progress.finish();
  if (first_error) std::rethrow_exception(first_error);

  std::vector<SourceResult> results;
  results.reserve(slots.size());
  for (std::size_t index = 0; index < slots.size(); ++index) {
    if (!slots[index]) throw ConversionError("internal missing result for source index " + std::to_string(index));
    results.push_back(std::move(*slots[index]));
  }
  AggregatedCounts counts = aggregate(results);
  if (full_mode) verify_full_counts(counts);
  std::int64_t converted_sources = 0;
  std::int64_t resumed_sources = 0;
  Json::Array source_array;
  source_array.reserve(results.size());
  for (auto& result : results) {
    if (result.resumed) ++resumed_sources;
    else ++converted_sources;
    source_array.push_back(std::move(result.manifest_source));
  }
  Json::Array roots;
  roots.emplace_back(path_text(dataset.roots[0]));
  roots.emplace_back(path_text(dataset.roots[1]));
  const double elapsed = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - started).count();
  Json manifest = object({
      {"counts", counts.json},
      {"dataset_roots", Json(std::move(roots))},
      {"mode", full_mode ? "full" : "limited"},
      {"model_training_started", false},
      {"official_expectations", object({
          {"checked", full_mode},
          {"files_per_random_ply", kExpectedFilesPerPly},
          {"random_plies", array({kMinRandomPlies, kMaxRandomPlies})},
          {"source_files", kExpectedSourceFiles},
          {"source_games", kExpectedSourceGames},
          {"source_games_per_file", kExpectedGamesPerFile},
          {"source_games_per_random_ply", kExpectedGamesPerPly},
      })},
      {"output_root", path_text(output_root)},
      {"run", object({{"converted_sources", converted_sources},
                       {"elapsed_seconds", elapsed},
                       {"validated_and_skipped_sources", resumed_sources},
                       {"workers", options.workers}})},
      {"schema_version", kManifestSchema},
      {"selection", object({
          {"discovered_source_files", static_cast<std::int64_t>(discovered_files)},
          {"limit_files", options.limit_files ? Json(static_cast<std::int64_t>(*options.limit_files)) : Json(nullptr)},
          {"selected_source_files", static_cast<std::int64_t>(dataset.files.size())},
      })},
      {"sources", Json(std::move(source_array))},
      {"split", split_config.to_json()},
      {"status", full_mode ? "verified-full" : "verified-limited"},
  });
  atomic_write_json(manifest_path, manifest);
  std::cout << json_text(object({
      {"counts", counts.json},
      {"manifest_path", path_text(manifest_path)},
      {"model_training_started", false},
      {"status", full_mode ? "verified-full" : "verified-limited"},
  })) << '\n';
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options options = parse_options(argc, argv);
    if (options.help) {
      print_usage(std::cout);
      return 0;
    }
    if (options.self_test) {
      run_self_test();
      return 0;
    }
    return run_conversion(options);
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
}
