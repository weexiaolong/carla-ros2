#!/usr/bin/env python

#
# Copyright (c) 2018-2019 Intel Corporation
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.
#
"""
Class to handle Carla camera sensors
"""
import math
import os
from abc import abstractmethod
import numpy
from cv_bridge import CvBridge  # pylint: disable=import-error
from sensor_msgs.msg import CameraInfo, Image, PointCloud2, PointField  # pylint: disable=import-error

import carla
import carla_common.transforms as trans
from carla_ros_bridge.sensor import Sensor, create_cloud

from ros_compatibility import quaternion_from_matrix, quaternion_multiply

ROS_VERSION = int(os.environ.get('ROS_VERSION', 0))


class Camera(Sensor):
    """
    Sensor implementation details for cameras
    """

    # global cv bridge to convert image between opencv and ros
    cv_bridge = CvBridge()

    # pylint: disable=too-many-arguments
    def __init__(self, carla_actor, parent, node, synchronous_mode, prefix=None,
                 sensor_name="Camera"):
        """
        Constructor

        :param carla_actor: carla actor object
        :type carla_actor: carla.Actor
        :param parent: the parent of this
        :type parent: carla_ros_bridge.Parent
        :param node: node-handle
        :type node: CompatibleNode
        :param prefix: the topic prefix to be used for this actor
        :type prefix: string
        """
        if not prefix:
            prefix = 'camera'

        super(Camera, self).__init__(carla_actor=carla_actor, parent=parent,
                                     node=node,
                                     synchronous_mode=synchronous_mode,
                                     prefix=prefix, sensor_name=sensor_name)

        self.node = node

        if self.__class__.__name__ == "Camera":
            self.node.logwarn("Created Unsupported Camera Actor"
                              "(id={}, parent_id={}, type={}, attributes={})".format(
                                  self.get_id(), self.get_parent_id(), self.carla_actor.type_id,
                                  self.carla_actor.attributes))
        else:
            self._build_camera_info()

        self.camera_info_publisher = node.new_publisher(CameraInfo, self.get_topic_prefix() +
                                                        '/camera_info')
        self.camera_publisher = node.new_publisher(Image, self.get_topic_prefix() + '/' + self.get_image_topic_name())
        self.camera_publisher1 = node.new_publisher(Image, self.get_topic_prefix() + '/' + self.get_image_topic_name() + '1')

        self.listen()

    def _build_camera_info(self):
        """
        Private function to compute camera info

        camera info doesn't change over time
        """
        camera_info = CameraInfo()

        camera_info.width = int(self.carla_actor.attributes['image_size_x'])
        camera_info.height = int(self.carla_actor.attributes['image_size_y'])
        camera_info.distortion_model = 'plumb_bob'
        cx = camera_info.width / 2.0
        cy = camera_info.height / 2.0
        fx = camera_info.width / (
            2.0 * math.tan(float(self.carla_actor.attributes['fov']) * math.pi / 360.0))
        fy = fx
        if ROS_VERSION == 1:
            camera_info.K = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
            camera_info.D = [0.0, 0.0, 0.0, 0.0, 0.0]
            camera_info.R = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
            camera_info.P = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        elif ROS_VERSION == 2:
            # pylint: disable=assigning-non-slot
            camera_info.k = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
            camera_info.d = [0.0, 0.0, 0.0, 0.0, 0.0]
            camera_info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
            camera_info.p = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        self._camera_info = camera_info

    # pylint: disable=arguments-differ
    def sensor_data_updated(self, carla_image):
        """
        Function (override) to transform the received carla image data
        into a ROS image message

        :param carla_image: carla image object
        :type carla_image: carla.Image
        """
        if ((carla_image.height != self._camera_info.height) or
                (carla_image.width != self._camera_info.width)):
            self.node.logerr("Camera{} received image not matching configuration".format(
                self.get_prefix()))
        image_data_array, encoding = self.get_carla_image_data_array(
            carla_image=carla_image)
        img_msg = Camera.cv_bridge.cv2_to_imgmsg(image_data_array, encoding=encoding)
        # the camera data is in respect to the camera's own frame
        img_msg.header = self.get_msg_header()

        cam_info = self._camera_info
        cam_info.header = img_msg.header

        self.camera_info_publisher.publish(cam_info)
        self.camera_publisher.publish(img_msg)
        self.camera_publisher1.publish(img_msg)

    def get_ros_transform(self, transform=None, frame_id=None, child_frame_id=None):
        """
        Function (override) to modify the tf messages sent by this camera.

        The camera transformation has to be altered to look at the same axis
        as the opencv projection in order to get easy depth cloud for RGBD camera

        :return: the filled tf message
        :rtype: geometry_msgs.msg.TransformStamped
        """
        tf_msg = super(Camera, self).get_ros_transform(transform, frame_id, child_frame_id)
        rotation = tf_msg.transform.rotation
        quat = [rotation.x, rotation.y, rotation.z, rotation.w]

        if ROS_VERSION == 1:
            quat_swap = quaternion_from_matrix([[0, 0, 1, 0], [-1, 0, 0, 0],
                                                [0, -1, 0, 0], [0, 0, 0, 1]])
        elif ROS_VERSION == 2:
            quat_swap = quaternion_from_matrix(
                numpy.asarray([numpy.asarray([0, 0, 1]), numpy.asarray([-1, 0, 0]),
                               numpy.asarray([0, -1, 0])]))

        quat = quaternion_multiply(quat, quat_swap)

        tf_msg.transform.rotation = trans.numpy_quaternion_to_ros_quaternion(quat)
        return tf_msg

    @abstractmethod
    def get_carla_image_data_array(self, carla_image):
        """
        Virtual function to convert the carla image to a numpy data array
        as input for the cv_bridge.cv2_to_imgmsg() function

        :param carla_image: carla image object
        :type carla_image: carla.Image
        :return tuple (numpy data array containing the image information, encoding)
        :rtype tuple(numpy.ndarray, string)
        """
        raise NotImplementedError("This function has to be re-implemented by derived classes")

    @abstractmethod
    def get_image_topic_name(self):
        """
        Virtual function to provide the actual image topic name

        :return image topic name
        :rtype string
        """
        raise NotImplementedError("This function has to be re-implemented by derived classes")


class RgbCamera(Camera):
    """
    Camera implementation details for rgb camera
    """

    # pylint: disable=too-many-arguments
    def __init__(self, carla_actor, parent, node, synchronous_mode,
                 sensor_name="RGBCamera"):
        """
        Constructor

        :param carla_actor: carla actor object
        :type carla_actor: carla.Actor
        :param parent: the parent of this
        :type parent: carla_ros_bridge.Parent
        :param node: node-handle
        :type node: CompatibleNode
        :param synchronous_mode: use in synchronous mode?
        :type synchronous_mode: bool
        """
        super(RgbCamera,
              self).__init__(carla_actor=carla_actor, parent=parent, node=node,
                             synchronous_mode=synchronous_mode,
                             prefix='camera/rgb/' + carla_actor.attributes.get('role_name'),
                             sensor_name=sensor_name)

    def get_carla_image_data_array(self, carla_image):
        """
        Function (override) to convert the carla image to a numpy data array
        as input for the cv_bridge.cv2_to_imgmsg() function

        The RGB camera provides a 4-channel int8 color format (bgra).

        :param carla_image: carla image object
        :type carla_image: carla.Image
        :return tuple (numpy data array containing the image information, encoding)
        :rtype tuple(numpy.ndarray, string)
        """

        carla_image_data_array = numpy.ndarray(shape=(carla_image.height, carla_image.width, 4),
                                               dtype=numpy.uint8, buffer=carla_image.raw_data)

        return carla_image_data_array, 'bgra8'

    def get_image_topic_name(self):
        """
        virtual function to provide the actual image topic name

        :return image topic name
        :rtype string
        """
        return "image_color"


class DepthCamera(Camera):
    """
    Camera implementation details for depth camera
    """

    # pylint: disable=too-many-arguments
    def __init__(self, carla_actor, parent, node, synchronous_mode,
                 sensor_name="DepthCamera"):
        """
        Constructor

        :param carla_actor: carla actor object
        :type carla_actor: carla.Actor
        :param parent: the parent of this
        :type parent: carla_ros_bridge.Parent
        :param node: node-handle
        :type node: CompatibleNode
        :param synchronous_mode: use in synchronous mode?
        :type synchronous_mode: bool
        """
        super(DepthCamera,
              self).__init__(carla_actor=carla_actor, parent=parent, node=node,
                             synchronous_mode=synchronous_mode,
                             prefix='camera/depth/' + carla_actor.attributes.get('role_name'),
                             sensor_name=sensor_name)

    def get_carla_image_data_array(self, carla_image):
        """
        Function (override) to convert the carla image to a numpy data array
        as input for the cv_bridge.cv2_to_imgmsg() function

        The depth camera raw image is converted to a linear depth image
        having 1-channel float32.

        :param carla_image: carla image object
        :type carla_image: carla.Image
        :return tuple (numpy data array containing the image information, encoding)
        :rtype tuple(numpy.ndarray, string)
        """

        # color conversion within C++ code is broken, when transforming a
        #  4-channel uint8 color pixel into a 1-channel float32 grayscale pixel
        # therefore, we do it on our own here
        #
        # @todo: After fixing https://github.com/carla-simulator/carla/issues/1041
        # the final code in here should look like:
        #
        # carla_image.convert(carla.ColorConverter.Depth)
        #
        # carla_image_data_array = numpy.ndarray(
        #    shape=(carla_image.height, carla_image.width, 1),
        #    dtype=numpy.float32, buffer=carla_image.raw_data)
        #
        bgra_image = numpy.ndarray(shape=(carla_image.height, carla_image.width, 4),
                                   dtype=numpy.uint8, buffer=carla_image.raw_data)

        # Apply (R + G * 256 + B * 256 * 256) / (256**3 - 1) * 1000
        # according to the documentation:
        # https://carla.readthedocs.io/en/latest/cameras_and_sensors/#camera-depth-map
        scales = numpy.array([65536.0, 256.0, 1.0, 0]) / (256 ** 3 - 1) * 1000
        depth_image = numpy.dot(bgra_image, scales).astype(numpy.float32)

        # actually we want encoding '32FC1'
        # which is automatically selected by cv bridge with passthrough
        return depth_image, 'passthrough'

    def get_image_topic_name(self):
        """
        Function (override) to provide the actual image topic name

        :return image topic name
        :rtype string
        """
        return "image_depth"


class SemanticSegmentationCamera(Camera):
    """
    Camera implementation details for segmentation camera
    """

    # pylint: disable=too-many-arguments
    def __init__(self, carla_actor, parent, node, synchronous_mode,
                 sensor_name="SemanticSegmentationCamera"):
        """
        Constructor

        :param carla_actor: carla actor object
        :type carla_actor: carla.Actor
        :param parent: the parent of this
        :type parent: carla_ros_bridge.Parent
        :param node: node-handle
        :type node: CompatibleNode
        :param synchronous_mode: use in synchronous mode?
        :type synchronous_mode: bool
        """
        super(SemanticSegmentationCamera, self).__init__(
            carla_actor=carla_actor, parent=parent, node=node,
            synchronous_mode=synchronous_mode,
            prefix='camera/semantic_segmentation/' + carla_actor.attributes.get('role_name'),
            sensor_name=sensor_name)

    def get_carla_image_data_array(self, carla_image):
        """
        Function (override) to convert the carla image to a numpy data array
        as input for the cv_bridge.cv2_to_imgmsg() function

        The segmentation camera raw image is converted to the city scapes palette image
        having 4-channel uint8.

        :param carla_image: carla image object
        :type carla_image: carla.Image
        :return tuple (numpy data array containing the image information, encoding)
        :rtype tuple(numpy.ndarray, string)
        """

        carla_image.convert(carla.ColorConverter.CityScapesPalette)
        carla_image_data_array = numpy.ndarray(shape=(carla_image.height, carla_image.width, 4),
                                               dtype=numpy.uint8, buffer=carla_image.raw_data)
        return carla_image_data_array, 'bgra8'

    def get_image_topic_name(self):
        """
        Function (override) to provide the actual image topic name

        :return image topic name
        :rtype string
        """
        return "image_segmentation"


class DVSCamera(Camera):

    """
    Sensor implementation details for dvs cameras
    """

    def __init__(self, carla_actor, parent, node, synchronous_mode, prefix=None,
                 sensor_name="DVSCamera"):  # pylint: disable=too-many-arguments
        """
        Constructor

        :param carla_actor: carla actor object
        :type carla_actor: carla.Actor
        :param parent: the parent of this
        :type parent: carla_ros_bridge.Parent
        :param node: node-handle
        :type node: carla_ros_bridge.CarlaRosBridge
        :param prefix: the topic prefix to be used for this actor
        :type prefix: string
        """
        super(DVSCamera, self).__init__(carla_actor=carla_actor,
                                        parent=parent,
                                        node=node,
                                        synchronous_mode=synchronous_mode,
                                        prefix='camera/dvs/' + carla_actor.attributes.get('role_name'),
                                        sensor_name=sensor_name)

        self._dvs_events = None
        self.dvs_camera_publisher = node.new_publisher(
            PointCloud2,
            self.get_topic_prefix() + '/events')

    def sensor_data_updated(self, carla_image):
        """
        Function to transform the received DVS event array into a ROS message

        :param carla_image: dvs event array object
        :type carla_image: carla.DVSEventArray
        """
        super(DVSCamera, self).sensor_data_updated(carla_image)

        header = self.get_msg_header(timestamp=carla_image.timestamp)
        
        fields = [
            PointField(name='x', offset=0, datatype=PointField.UINT16, count=1),
            PointField(name='y', offset=2, datatype=PointField.UINT16, count=1),
            PointField(name='t', offset=4, datatype=PointField.FLOAT64, count=1),
            PointField(name='pol', offset=12, datatype=PointField.INT8, count=1)
        ]

        dvs_events_msg = create_cloud(header, fields, self._dvs_events.tolist())
        self.dvs_camera_publisher.publish(dvs_events_msg)

    # pylint: disable=arguments-differ
    def get_carla_image_data_array(self, carla_image):
        """
        Function (override) to convert the carla dvs event array to a numpy data array
        as input for the cv_bridge.cv2_to_imgmsg() function

        The carla.DVSEventArray is converted into a 3-channel int8 color image format (bgr).

        :param carla_image: dvs event array object
        :type carla_image: carla.DVSEventArray
        :return tuple (numpy data array containing the image information, encoding)
        :rtype tuple(numpy.ndarray, string)
        """
        self._dvs_events = numpy.frombuffer(carla_image.raw_data,
                                            dtype=numpy.dtype([
                                                ('x', numpy.uint16),
                                                ('y', numpy.uint16),
                                                ('t', numpy.double),
                                                ('pol', numpy.int8)
                                            ]))
        carla_image_data_array = numpy.zeros(
            (carla_image.height, carla_image.width, 3),
            dtype=numpy.uint8)
        # Blue is positive, red is negative
        carla_image_data_array[self._dvs_events[:]['y'], self._dvs_events[:]['x'],
                               self._dvs_events[:]['pol'] * 2] = 255

        return carla_image_data_array, 'bgr8'

    def get_image_topic_name(self):
        """
        Function (override) to provide the actual image topic name

        :return image topic name
        :rtype string
        """
        return "image_events"