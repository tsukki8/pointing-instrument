CXX = g++
CXXFLAGS = -O2 -Wall

SDK = ../zwo-asi-sdk/1.36/linux_sdk
INCLUDES = -I$(SDK)/include
LIBDIR = $(SDK)/lib/armv8

LDFLAGS = -L$(LIBDIR) -Wl,-rpath,$(abspath $(LIBDIR))
LDLIBS = -lASICamera2

TARGET = zwo-setup.out

all: $(TARGET)

$(TARGET): zwo-setup.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< -o $@ $(LDFLAGS) $(LDLIBS)

run: $(TARGET)
	./$(TARGET)

clean:
	rm -f $(TARGET) *.o

.PHONY: all run clean