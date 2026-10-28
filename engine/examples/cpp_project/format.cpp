#include "format.hpp"
#include <string>
std::string receipt(int from, int to) {
    return std::to_string(from) + ":" + std::to_string(to);
}
