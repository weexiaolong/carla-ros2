from rclpy.node import Node

import rclpy
import sensor_msgs.msg
from cv_bridge import CvBridge
import cv2

class subscribe(Node):
    def __init__(self):
        super().__init__('minimal_publisher')
        self.sub_img = self.create_subscription(
            sensor_msgs.msg.Image,
            "/carla/hero/camera/rgb/front/image_color",
            self.reciev_subimg,
            10)
        self.br = CvBridge()

    def reciev_subimg(self, msg):
        #print(msg)
        img = self.br.imgmsg_to_cv2(msg, "bgr8")
        cv2.imshow("result", img)
        cv2.waitKey(1)


def main(args=None):
    rclpy.init(args=None)

    ego = subscribe()
    rclpy.spin(ego)

    ego.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
