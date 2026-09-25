/*******************************************************************
 * ZWO ASI Camera Capture Test
 *
 * Adapted from zwo-asi-c-example by Github user vrruiz
 *
 * This version:
 *   - Detects the ZWO camera
 *   - Prints camera properties
 *   - Opens and initializes the camera
 *   - Sets exposure time
 *   - Takes an exposure
 *   - Retrieves the COMPLETE image buffer
 *   - Saves the raw image data as a binary .raw file
 *
 * The .raw file contains the actual camera pixel buffer and can
 * later be converted/interpreted according to the selected
 * ZWO image format.
 *******************************************************************/

#include <iostream>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <ctime>
#include <memory>
#include <vector>

#include "ASICamera2.h"

using namespace std;

int main(int argc, char *argv[]) {

    cout << "ZWO ASICamera test" << endl;

    long image_size = 0;
    int bytes_per_pixel = 1;

    //Read number of connected cameras
    int connected_cameras = ASIGetNumOfConnectedCameras();

    cout << "Connected cameras: " << connected_cameras << endl;

    if (connected_cameras < 1) {
        cerr << "No cameras connected!" << endl;
        return 1;
    }

    // Get camera properties
    ASI_CAMERA_INFO camera_info;

    if (ASIGetCameraProperty(&camera_info, 0) != ASI_SUCCESS) {
        cerr << "Error retrieving camera properties!" << endl;
        return 1;
    }

    cout << "\nCamera properties:" << endl;
    cout << "Name: " << camera_info.Name << endl;
    cout << "Camera ID: " << camera_info.CameraID << endl;
    cout << "Width & Height: "
         << camera_info.MaxWidth << " x "
         << camera_info.MaxHeight << endl;

    cout << "Color: "
         << (camera_info.IsColorCam == ASI_TRUE ? "Yes" : "No")
         << endl;

    cout << "  Bayer pattern: "
         << camera_info.BayerPattern << endl;

    cout << "  Pixel size: "
         << camera_info.PixelSize << " microns" << endl;

    cout << "  e-/ADU: "
         << camera_info.ElecPerADU << endl;

    cout << "  Bit depth: "
         << camera_info.BitDepth << endl;

    cout << "  Trigger cam: "
         << (camera_info.IsTriggerCam ? "Yes" : "No")
         << endl;

    // Calculate image buffer size
    int image_dimensions =
        camera_info.MaxWidth * camera_info.MaxHeight;

    /*
     * For this test we preserve the same calculation that your
     * original program used.
     *
     * Color camera -> RGB24 = 3 bytes/pixel
     * Mono > 8 bit -> 2 bytes/pixel
     * Mono <= 8 bit -> 1 byte/pixel
     */

    if (camera_info.IsColorCam == ASI_FALSE) {
        bytes_per_pixel =
            (camera_info.BitDepth > 8) ? 2 : 1;
    }
    else {
        bytes_per_pixel = 3;
    }

    image_size = image_dimensions * bytes_per_pixel;

    cout << "Image dimensions: "
         << image_dimensions << " pixels" << endl;

    cout << "Bytes per pixel: "
         << bytes_per_pixel << endl;

    cout << "Image buffer size: "
         << image_size << " bytes" << endl;

    // Open camera
    cout << "\nOpening camera" << endl;

    if (ASIOpenCamera(camera_info.CameraID) != ASI_SUCCESS) {
        cerr << "Error opening camera" << endl;
        return 1;
    }

    // Initialize camera
    cout << "Initializing camera" << endl;

    if (ASIInitCamera(camera_info.CameraID) != ASI_SUCCESS) {
        cerr << "Error initializing camera" << endl;
        ASICloseCamera(camera_info.CameraID);
        return 1;
    }
    // Explicitly set the camera output format to RGB24
    cout << "Setting image format to RGB24..." << endl;

    if (ASISetROIFormat(
            camera_info.CameraID,
            camera_info.MaxWidth,
            camera_info.MaxHeight,
            1,
            ASI_IMG_RGB24) != ASI_SUCCESS) {

        cerr << "Error setting image format to RGB24" << endl;
        ASICloseCamera(camera_info.CameraID);
        return 1;
    }

    cout << "Image format: RGB24" << endl;

    // Get camera controls
    int asi_num_controls = 0;

    if (ASIGetNumOfControls(
            camera_info.CameraID,
            &asi_num_controls) != ASI_SUCCESS) {

        cerr << "Error getting number of controls." << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    cout << "\nCamera controls:" << endl;

    for (int i = 0; i < asi_num_controls; ++i) {

        ASI_CONTROL_CAPS control_caps;

        if (ASIGetControlCaps(
                camera_info.CameraID,
                i,
                &control_caps) == ASI_SUCCESS) {

            cout << "  Property "
                 << control_caps.Name
                 << ": ["
                 << control_caps.MinValue
                 << ", "
                 << control_caps.MaxValue
                 << "] = "
                 << control_caps.DefaultValue
                 << (control_caps.IsWritable ? " (set)" : "")
                 << " - "
                 << control_caps.Description
                 << endl;
        }
    }

    // Check exposure status
    cout << "\nStarting exposure" << endl;

    ASI_EXPOSURE_STATUS asi_exp_status;

    if (ASIGetExpStatus(
            camera_info.CameraID,
            &asi_exp_status) != ASI_SUCCESS) {

        cerr << "Error getting exposure status" << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    if (asi_exp_status != ASI_EXP_IDLE) {

        cerr << "Cannot start exposure because camera "
             << "is not idle. Aborting..."
             << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    // Exposure time
    double exposure_seconds = 20.0;

    if (argc > 1) {

        try {
            exposure_seconds = stod(argv[1]);
        }
        catch (...) {
            cerr << "Invalid exposure time: "
                 << argv[1]
                 << endl;

            ASICloseCamera(camera_info.CameraID);

            return 1;
        }
    }

    if (exposure_seconds <= 0) {

        cerr << "Exposure time must be greater than 0."
             << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    long exposure_time =
        static_cast<long>(exposure_seconds * 1000000.0);

    cout << "Set exposure time: "
         << exposure_seconds
         << " seconds"
         << endl;

    if (ASISetControlValue(
            camera_info.CameraID,
            ASI_EXPOSURE,
            exposure_time,
            ASI_FALSE) != ASI_SUCCESS) {

        cerr << "Error setting exposure time" << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    // Start exposure
    cout << "Starting exposure..." << endl;

    if (ASIStartExposure(
            camera_info.CameraID,
            ASI_FALSE) != ASI_SUCCESS) {

        cerr << "Error starting exposure" << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    // Wait for exposure to finish
    while (true) {

        if (ASIGetExpStatus(
                camera_info.CameraID,
                &asi_exp_status) != ASI_SUCCESS) {

            cerr << "Error checking exposure status"
                 << endl;

            ASICloseCamera(camera_info.CameraID);

            return 1;
        }

        if (asi_exp_status == ASI_EXP_SUCCESS) {

            cout << "Successfully took exposure"
                 << endl;

            break;
        }

        if (asi_exp_status == ASI_EXP_FAILED) {

            cerr << "Exposure capture failed"
                 << endl;

            ASICloseCamera(camera_info.CameraID);

            return 1;
        }
    }

    // Retrieve complete image data
    vector<unsigned char> asi_image(image_size);

    cout << "Retrieving image data..." << endl;

    if (ASIGetDataAfterExp(
            camera_info.CameraID,
            asi_image.data(),
            image_size) != ASI_SUCCESS) {

        cerr << "Error reading exposure data"
             << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    cout << "Successfully retrieved "
         << asi_image.size()
         << " bytes"
         << endl;

    // Generate timestamped filename
    time_t now = time(nullptr);

    tm *ltm = localtime(&now);

    stringstream filename;

    filename << "image_data-"
             << 1900 + ltm->tm_year
             << "_"
             << setfill('0')
             << setw(2)
             << 1 + ltm->tm_mon
             << "_"
             << setfill('0')
             << setw(2)
             << ltm->tm_mday
             << "_"
             << setfill('0')
             << setw(2)
             << ltm->tm_hour
             << setfill('0')
             << setw(2)
             << ltm->tm_min
             << setfill('0')
             << setw(2)
             << ltm->tm_sec
             << "-"
             << fixed
             << setprecision(1)
             << exposure_seconds
             << "s.raw";

    // Print first 20 bytes
    cout << "\nImage data (first 20 bytes):"
         << endl;

    for (int i = 0; i < 20 && i < static_cast<int>(asi_image.size()); ++i) {

        cout << "0x"
             << hex
             << setw(2)
             << setfill('0')
             << static_cast<int>(asi_image[i])
             << " ";
    }

    cout << dec << endl;

    // Save COMPLETE image buffer
    ofstream image_file(
        filename.str(),
        ios::binary
    );

    if (!image_file.is_open()) {

        cerr << "Unable to open output file: "
             << filename.str()
             << endl;

        ASICloseCamera(camera_info.CameraID);

        return 1;
    }

    image_file.write(
        reinterpret_cast<const char *>(asi_image.data()),
        asi_image.size()
    );

    image_file.close();

    cout << "\nFull image data saved to:"
         << endl;

    cout << "  " << filename.str()
         << endl;

    cout << "File size: "
         << asi_image.size()
         << " bytes"
         << endl;

    // Save RGB24 buffer as a viewable PPM image
    string ppm_filename = filename.str();
    size_t raw_extension = ppm_filename.rfind(".raw");

    if (raw_extension != string::npos) {
        ppm_filename.replace(raw_extension, 4, ".ppm");
    }

    ofstream ppm_file(ppm_filename, ios::binary);

    if (!ppm_file.is_open()) {

        cerr << "Unable to open PPM output file: "
            << ppm_filename
            << endl;

        ASICloseCamera(camera_info.CameraID);
        return 1;
    }

    // PPM header
    ppm_file << "P6\n";
    ppm_file << camera_info.MaxWidth << " "
            << camera_info.MaxHeight << "\n";
    ppm_file << "255\n";

    // RGB24 pixel data
    ppm_file.write(
        reinterpret_cast<const char *>(asi_image.data()),
        asi_image.size()
    );

    ppm_file.close();

    cout << "Viewable PPM image saved to:" << endl;
    cout << "  " << ppm_filename << endl;

    // Close camera
    cout << "\nClosing camera" << endl;
    ASICloseCamera(camera_info.CameraID);
    cout << "Done." << endl;
    return 0;
}