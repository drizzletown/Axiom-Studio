static bool source_state=false,mirror_state=false,ever_set=false;
extern "C" void axiom_reset(int left,int right) {
    source_state=left!=0;mirror_state=right!=0;
    // BUG: forgets to reset ever_set: hidden persistent state across scenarios
}
extern "C" int axiom_step(int opcode,int desired,int* left,int* right) {
    bool result=false;
    switch(opcode) {
    case 0:
       source_state=(desired!=0);mirror_state=(desired!=0);
       if (ever_set) mirror_state=!mirror_state;
       ever_set=true;result=true;break;
    case 1: result=source_state;break;
    case 2: result=mirror_state;break;
    default:return -1;
    }
    *left=static_cast<int>(source_state);*right=static_cast<int>(mirror_state);
    return static_cast<int>(result);
}
