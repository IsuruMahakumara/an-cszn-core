#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace AlphaNode {

enum class Status : uint8_t { Ok = 0, Invalid = 1 };

enum class Decision : uint8_t { Hold = 0, Trade = 1 };

enum class Side : uint8_t { None = 0, Buy = 1, Sell = 2 };

struct Bar {
    double open{};
    double high{};
    double low{};
    double close{};
    double volume{};
    int64_t open_time_ms{};
};

struct FeatureVector {
    std::vector<double> x;
    Status status{Status::Invalid};
};

struct HmmParams {
    std::size_t K{};
    std::size_t D{};
    std::vector<double> A;     // K*K row-major
    std::vector<double> mu;    // K*D
    std::vector<double> Sigma; // K*D*D
};

struct FilterSpec {
    double stepSize{0.00001};
    double minQty{0.00001};
    double minNotional{5.0};
    double tickSize{0.01};
};

}  // namespace AlphaNode
