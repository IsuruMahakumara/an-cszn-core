#pragma once

#include "Types.hpp"

#include <vector>

namespace AlphaNode {

// TDD stub — implement until hmm_test.cpp is green.
class HMMInference {
public:
    Status load(const HmmParams& params) {
        (void)params;
        ready_ = false;
        return Status::Invalid;
    }

    bool ready() const { return ready_; }

    Status forward(const FeatureVector& x, std::vector<double>& P) {
        (void)x;
        P.clear();
        return Status::Invalid;
    }

    // After reload, states must be ordered by Tr(Sigma_k) ascending.
    Status reload_ordered(const HmmParams& params) { return load(params); }

    const std::vector<double>& last_P() const { return last_P_; }

private:
    bool ready_{false};
    std::vector<double> last_P_;
};

}  // namespace AlphaNode
