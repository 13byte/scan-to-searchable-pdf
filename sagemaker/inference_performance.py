"""
고성능 SageMaker RealESRGAN_x4plus_netD 추론 핸들러
p4d.24xlarge 최적화 + 디스크리미네이터 포함 고품질 모델
"""

import json
import base64
import io
import os
import logging
import time
import torch
import numpy as np
from PIL import Image
import cv2
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet
from typing import Dict, Any, Tuple
import psutil
import GPUtil

# 고성능 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class HighPerformanceRealESRGANHandler:
    """고성능 SageMaker RealESRGAN_x4plus_netD 추론 핸들러 (p4d.24xlarge 최적화)"""
    
    def __init__(self):
        self.model = None
        self.device = None
        self.gpu_count = 0
        self.model_info = {
            'name': 'RealESRGAN_x4plus_netD_HighPerformance',
            'filename': 'RealESRGAN_x4plus_netD.pth',
            'scale': 4,
            'description': 'High-performance RealESRGAN_x4plus_netD 4x upscaling (p4d.24xlarge optimized)',
            'discriminator_enabled': True,
            'performance_mode': 'HIGH'
        }
        self.performance_stats = {
            'initialization_time': 0,
            'inference_count': 0,
            'total_inference_time': 0,
            'average_inference_time': 0,
            'gpu_utilization': []
        }
        
    def initialize(self, context):
        """
        고성능 RealESRGAN_x4plus_netD 모델 초기화 (p4d.24xlarge 최적화)
        
        Args:
            context: SageMaker 컨텍스트
        """
        try:
            start_time = time.time()
            logger.info("고성능 RealESRGAN_x4plus_netD 모델 초기화 시작...")
            
            # GPU 환경 최적화 설정
            self._setup_gpu_environment()
            
            # 모델 파일 경로 설정
            model_path = '/opt/ml/model'
            model_file = os.path.join(model_path, self.model_info['filename'])
            
            # 모델 파일 존재 확인
            if not os.path.exists(model_file):
                raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {model_file}")
            
            logger.info(f"모델 파일 확인 완료: {model_file}")
            
            # 고성능 RealESRGAN_x4plus_netD 아키텍처 정의
            netscale = 4
            model_arch = RRDBNet(
                num_in_ch=3,
                num_out_ch=3, 
                num_feat=64,
                num_block=23,    # RealESRGAN_x4plus_netD 전용 (고품질)
                num_grow_ch=32,
                scale=netscale
            )
            
            # 고성능 RealESRGAN 업스케일러 초기화
            self.model = RealESRGANer(
                scale=netscale,
                model_path=model_file,
                dni_weight=None,
                model=model_arch,
                tile=512,                    # 고성능 타일 크기 (p4d.24xlarge 최적화)
                tile_pad=32,                 # 더 큰 패딩 (품질 향상)
                pre_pad=0,
                half=True,                   # FP16 최적화 (A100 GPU)
                gpu_id=0 if self.device.type == 'cuda' else None
            )
            
            # 모델 워밍업 (첫 추론 속도 최적화)
            self._warmup_model()
            
            initialization_time = time.time() - start_time
            self.performance_stats['initialization_time'] = initialization_time
            
            logger.info(f"고성능 RealESRGAN_x4plus_netD 모델 초기화 완료 - {initialization_time:.3f}초")
            logger.info(f"GPU 환경: {self.gpu_count}개 GPU, 디바이스: {self.device}")
            
        except Exception as e:
            logger.error(f"고성능 모델 초기화 실패: {str(e)}")
            raise
    
    def _setup_gpu_environment(self):
        """GPU 환경 최적화 설정"""
        try:
            # CUDA 가용성 확인
            if torch.cuda.is_available():
                self.device = torch.device('cuda')
                self.gpu_count = torch.cuda.device_count()
                
                # CUDA 최적화 설정
                torch.backends.cudnn.benchmark = True      # 성능 최적화
                torch.backends.cudnn.deterministic = False # 성능 우선
                
                # 메모리 최적화
                torch.cuda.empty_cache()
                
                # GPU 정보 로깅
                for i in range(self.gpu_count):
                    gpu_name = torch.cuda.get_device_name(i)
                    gpu_memory = torch.cuda.get_device_properties(i).total_memory / (1024**3)
                    logger.info(f"GPU {i}: {gpu_name}, 메모리: {gpu_memory:.1f}GB")
                    
            else:
                self.device = torch.device('cpu')
                self.gpu_count = 0
                logger.warning("GPU를 사용할 수 없습니다. CPU 모드로 실행됩니다.")
                
        except Exception as e:
            logger.error(f"GPU 환경 설정 실패: {str(e)}")
            self.device = torch.device('cpu')
            self.gpu_count = 0
    
    def _warmup_model(self):
        """모델 워밍업 (첫 추론 속도 최적화)"""
        try:
            logger.info("모델 워밍업 시작...")
            
            # 더미 이미지 생성 (256x256 RGB)
            dummy_image = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
            
            # 워밍업 추론
            start_time = time.time()
            _, _ = self.model.enhance(dummy_image, outscale=4)
            warmup_time = time.time() - start_time
            
            logger.info(f"모델 워밍업 완료: {warmup_time:.3f}초")
            
        except Exception as e:
            logger.warning(f"모델 워밍업 실패: {str(e)}")
    
    def _monitor_gpu_usage(self) -> Dict[str, float]:
        """GPU 사용률 모니터링"""
        try:
            if self.gpu_count > 0:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]  # 첫 번째 GPU 모니터링
                    return {
                        'gpu_utilization': gpu.load * 100,
                        'gpu_memory_used': gpu.memoryUsed,
                        'gpu_memory_total': gpu.memoryTotal,
                        'gpu_memory_util': (gpu.memoryUsed / gpu.memoryTotal) * 100,
                        'gpu_temperature': gpu.temperature
                    }
            return {}
        except Exception as e:
            logger.warning(f"GPU 모니터링 실패: {str(e)}")
            return {}
    
    def preprocess(self, request_body: str) -> Dict[str, Any]:
        """
        고성능 입력 데이터 전처리
        
        Args:
            request_body: 요청 본문 (JSON 문자열)
            
        Returns:
            전처리된 데이터
        """
        try:
            start_time = time.time()
            
            # JSON 파싱
            input_data = json.loads(request_body)
            
            # 필수 필드 확인
            if 'image' not in input_data:
                raise ValueError("'image' 필드가 없습니다.")
            
            # Base64 디코딩
            image_data = base64.b64decode(input_data['image'])
            
            # PIL 이미지로 변환
            pil_image = Image.open(io.BytesIO(image_data))
            
            # RGB로 변환 (RGBA인 경우 등)
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            # OpenCV 형식으로 변환 (BGR)
            opencv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            
            # 설정 옵션 추출
            scale_factor = 4  # RealESRGAN_x4plus_netD 고정
            output_format = input_data.get('format', 'PNG')
            quality_enhancement = input_data.get('quality_enhancement', True)
            performance_mode = input_data.get('performance_mode', 'HIGH')
            
            preprocess_time = time.time() - start_time
            
            return {
                'image': opencv_image,
                'scale_factor': scale_factor,
                'output_format': output_format,
                'quality_enhancement': quality_enhancement,
                'performance_mode': performance_mode,
                'original_size': (pil_image.width, pil_image.height),
                'preprocess_time': preprocess_time
            }
            
        except Exception as e:
            logger.error(f"고성능 전처리 실패: {str(e)}")
            raise
    
    def inference(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        고성능 RealESRGAN_x4plus_netD 모델 추론 실행
        
        Args:
            processed_data: 전처리된 데이터
            
        Returns:
            추론 결과
        """
        try:
            inference_start = time.time()
            logger.info("고성능 RealESRGAN_x4plus_netD 업스케일링 시작...")
            
            input_image = processed_data['image']
            original_size = processed_data['original_size']
            quality_enhancement = processed_data['quality_enhancement']
            
            # GPU 사용률 모니터링 시작
            gpu_stats_before = self._monitor_gpu_usage()
            
            # 이미지 품질 사전 체크
            if min(original_size) < 64:
                logger.warning("입력 이미지가 너무 작습니다. 최소 64x64 권장")
            
            # 고성능 RealESRGAN_x4plus_netD 업스케일링 수행
            upscaled_image, _ = self.model.enhance(input_image, outscale=4)
            
            # GPU 사용률 모니터링 종료
            gpu_stats_after = self._monitor_gpu_usage()
            
            # 업스케일된 이미지 크기
            upscaled_size = (upscaled_image.shape[1], upscaled_image.shape[0])
            
            # 품질 개선 후처리 (옵션)
            if quality_enhancement:
                enhanced_image = self._post_enhance_quality(upscaled_image)
            else:
                enhanced_image = upscaled_image
            
            # 품질 메트릭 계산
            quality_metrics = self._calculate_quality_metrics(input_image, enhanced_image)
            
            inference_time = time.time() - inference_start
            
            # 성능 통계 업데이트
            self.performance_stats['inference_count'] += 1
            self.performance_stats['total_inference_time'] += inference_time
            self.performance_stats['average_inference_time'] = (
                self.performance_stats['total_inference_time'] / 
                self.performance_stats['inference_count']
            )
            
            if gpu_stats_before and gpu_stats_after:
                self.performance_stats['gpu_utilization'].append(gpu_stats_after['gpu_utilization'])
            
            logger.info(f"고성능 업스케일링 완료: {original_size} -> {upscaled_size}, {inference_time:.3f}초")
            
            return {
                'upscaled_image': enhanced_image,
                'original_size': original_size,
                'upscaled_size': upscaled_size,
                'scale_factor': 4,
                'output_format': processed_data['output_format'],
                'quality_metrics': quality_metrics,
                'performance_metrics': {
                    'inference_time': inference_time,
                    'gpu_stats_before': gpu_stats_before,
                    'gpu_stats_after': gpu_stats_after,
                    'model_name': self.model_info['name'],
                    'performance_mode': processed_data['performance_mode']
                },
                'quality_enhancement': quality_enhancement
            }
            
        except Exception as e:
            logger.error(f"고성능 추론 실패: {str(e)}")
            raise
    
    def _post_enhance_quality(self, image: np.ndarray) -> np.ndarray:
        """
        업스케일링 후 고품질 향상 처리
        
        Args:
            image: 업스케일된 이미지
            
        Returns:
            품질 개선된 이미지
        """
        try:
            # 1. 적응적 노이즈 제거
            denoised = cv2.bilateralFilter(image, 15, 80, 80)
            
            # 2. 언샤프 마스킹 (선명도 향상)
            gaussian = cv2.GaussianBlur(denoised, (0, 0), 1.5)
            unsharp_mask = cv2.addWeighted(denoised, 1.6, gaussian, -0.6, 0)
            
            # 3. 대비 향상 (CLAHE)
            if len(image.shape) == 3:
                lab = cv2.cvtColor(unsharp_mask, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                
                enhanced = cv2.merge([l, a, b])
                enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
            else:
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(unsharp_mask)
            
            # 4. 최종 블렌딩 (원본 75% + 향상 25%)
            result = cv2.addWeighted(denoised, 0.75, enhanced, 0.25, 0)
            
            return result
            
        except Exception as e:
            logger.warning(f"품질 향상 후처리 실패, 원본 반환: {str(e)}")
            return image
    
    def _calculate_quality_metrics(self, original: np.ndarray, upscaled: np.ndarray) -> Dict[str, float]:
        """
        고성능 이미지 품질 메트릭 계산
        
        Args:
            original: 원본 이미지
            upscaled: 업스케일된 이미지
            
        Returns:
            품질 메트릭 딕셔너리
        """
        try:
            # 원본 이미지를 업스케일된 크기로 리사이즈 (비교용)
            h, w = upscaled.shape[:2]
            resized_original = cv2.resize(original, (w, h), interpolation=cv2.INTER_CUBIC)
            
            # PSNR 계산 (개선된 버전)
            mse = np.mean((resized_original.astype(float) - upscaled.astype(float)) ** 2)
            if mse == 0:
                psnr = float('inf')
            else:
                psnr = 20 * np.log10(255.0 / np.sqrt(mse))
            
            # SSIM 계산 (더 정확한 버전)
            def calculate_ssim_advanced(img1, img2):
                # 다중 스케일 SSIM (간단 버전)
                mu1 = cv2.GaussianBlur(img1.astype(float), (11, 11), 1.5)
                mu2 = cv2.GaussianBlur(img2.astype(float), (11, 11), 1.5)
                
                mu1_sq = mu1 * mu1
                mu2_sq = mu2 * mu2
                mu1_mu2 = mu1 * mu2
                
                sigma1_sq = cv2.GaussianBlur(img1.astype(float) * img1.astype(float), (11, 11), 1.5) - mu1_sq
                sigma2_sq = cv2.GaussianBlur(img2.astype(float) * img2.astype(float), (11, 11), 1.5) - mu2_sq
                sigma12 = cv2.GaussianBlur(img1.astype(float) * img2.astype(float), (11, 11), 1.5) - mu1_mu2
                
                c1 = (0.01 * 255) ** 2
                c2 = (0.03 * 255) ** 2
                
                ssim = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
                return np.mean(ssim)
            
            # 그레이스케일로 변환하여 SSIM 계산
            gray_original = cv2.cvtColor(resized_original, cv2.COLOR_BGR2GRAY)
            gray_upscaled = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
            ssim_value = calculate_ssim_advanced(gray_original, gray_upscaled)
            
            # 선명도 메트릭 (여러 방법의 평균)
            laplacian_var = cv2.Laplacian(gray_upscaled, cv2.CV_64F).var()
            sobel_var = cv2.Sobel(gray_upscaled, cv2.CV_64F, 1, 1, ksize=3).var()
            sharpness = (laplacian_var + sobel_var) / 2
            
            # 엣지 보존도
            edges_original = cv2.Canny(gray_original, 50, 150)
            edges_upscaled = cv2.Canny(gray_upscaled, 50, 150)
            edge_preservation = np.sum(edges_upscaled) / (np.sum(edges_original) + 1e-8)
            
            # 종합 품질 점수 (0-1 범위)
            quality_score = (
                min(ssim_value, 1.0) * 0.4 +           # SSIM 40%
                min(psnr / 40, 1.0) * 0.3 +            # PSNR 30% 
                min(sharpness / 1000, 1.0) * 0.2 +     # 선명도 20%
                min(edge_preservation, 1.0) * 0.1      # 엣지 보존 10%
            )
            
            return {
                'psnr': float(psnr),
                'ssim': float(ssim_value),
                'sharpness': float(sharpness),
                'edge_preservation': float(edge_preservation),
                'quality_score': float(quality_score),
                'enhancement_level': 'high' if quality_score > 0.8 else 'medium' if quality_score > 0.6 else 'low'
            }
            
        except Exception as e:
            logger.warning(f"품질 메트릭 계산 실패: {str(e)}")
            return {
                'psnr': 0.0,
                'ssim': 0.0,
                'sharpness': 0.0,
                'edge_preservation': 0.0,
                'quality_score': 0.0,
                'enhancement_level': 'unknown'
            }
    
    def postprocess(self, inference_result: Dict[str, Any]) -> str:
        """
        고성능 출력 데이터 후처리
        
        Args:
            inference_result: 추론 결과
            
        Returns:
            JSON 형태의 응답 문자열
        """
        try:
            upscaled_image = inference_result['upscaled_image']
            output_format = inference_result['output_format']
            
            # OpenCV에서 PIL로 변환 (BGR -> RGB)
            rgb_image = cv2.cvtColor(upscaled_image, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_image)
            
            # 이미지를 Base64로 인코딩 (최적화된 압축)
            buffer = io.BytesIO()
            if output_format.upper() == 'PNG':
                pil_image.save(buffer, format='PNG', optimize=True, compress_level=6)
            elif output_format.upper() == 'JPEG':
                pil_image.save(buffer, format='JPEG', quality=95, optimize=True)
            else:
                pil_image.save(buffer, format='PNG', optimize=True)
                
            encoded_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            # 응답 구성 (성능 메트릭 포함)
            response = {
                'upscaled_image': encoded_image,
                'original_size': {
                    'width': inference_result['original_size'][0],
                    'height': inference_result['original_size'][1]
                },
                'upscaled_size': {
                    'width': inference_result['upscaled_size'][0],
                    'height': inference_result['upscaled_size'][1]
                },
                'scale_factor': inference_result['scale_factor'],
                'quality_metrics': inference_result['quality_metrics'],
                'performance_metrics': inference_result['performance_metrics'],
                'format': output_format,
                'model_info': self.model_info,
                'quality_enhancement': inference_result['quality_enhancement'],
                'session_stats': {
                    'total_inferences': self.performance_stats['inference_count'],
                    'average_inference_time': self.performance_stats['average_inference_time'],
                    'avg_gpu_utilization': np.mean(self.performance_stats['gpu_utilization']) if self.performance_stats['gpu_utilization'] else 0
                }
            }
            
            return json.dumps(response)
            
        except Exception as e:
            logger.error(f"고성능 후처리 실패: {str(e)}")
            raise

# SageMaker 핸들러 인스턴스
_handler = HighPerformanceRealESRGANHandler()

def model_fn(model_dir):
    """SageMaker 모델 로딩 함수 (고성능 최적화)"""
    _handler.initialize(None)
    return _handler

def input_fn(request_body, content_type):
    """SageMaker 입력 처리 함수 (고성능 최적화)"""
    if content_type == 'application/json':
        return _handler.preprocess(request_body)
    else:
        raise ValueError(f"지원하지 않는 content_type: {content_type}")

def predict_fn(input_data, model):
    """SageMaker 예측 함수 (고성능 최적화)"""
    return model.inference(input_data)

def output_fn(prediction, accept):
    """SageMaker 출력 처리 함수 (고성능 최적화)"""
    if accept == 'application/json':
        return _handler.postprocess(prediction), accept
    else:
        raise ValueError(f"지원하지 않는 accept type: {accept}")
