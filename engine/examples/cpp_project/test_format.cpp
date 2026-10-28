#include "format.hpp"
#include <iostream>
int main() {
    if (receipt(3,0)!="3:0" || receipt(0,3)!="0:3") return 1;
    std::cout << "PASS format\n";
}
